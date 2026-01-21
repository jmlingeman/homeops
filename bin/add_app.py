#!/usr/bin/env python3

import os

repo = input("Enter the docker repo:")
name = input("App name:")
namespace = input("App namespace:")
port = input("Port:")
ingress_type = input("Ingress type? 'internal' or 'external'")


persistence = input("Persistence? Valid values are: {{persistance_types}}")
configmap_q = input("Does the app require a configmap?")

if configmap_q == "y":
    hkv = input("Please enter key/value for configmap:")


helmrelease_yaml_template = f"""---
apiVersion: helm.toolkit.fluxcd.io/v2beta2
kind: HelmRelease
metadata:
  name: &app {{name}}
  namespace: media
spec:
  interval: 15m
  chart:
    spec:
      # renovate: registryUrl=https://bjw-s.github.io/helm-charts/
      chart: app-template
      version: 2.4.0
      sourceRef:
        kind: HelmRepository
        name: bjw-s
        namespace: flux-system
  maxHistory: 2
  install:
    createNamespace: true
    remediation:
      retries: 3
  upgrade:
    cleanupOnFail: true
    remediation:
      retries: 3
  uninstall:
    keepHistory: false
  values:
    controllers:
      main:
        annotations:
          reloader.stakater.com/auto: "true"

        containers:
          main:
            image:
              repository: {{repo}}
              tag: latest
            env:
              PORT: &port {{port}}
            probes:
              liveness: &probes
                enabled: true
                custom: true
                spec:
                  httpGet:
                    path: /
                    port: *port
                  initialDelaySeconds: 0
                  periodSeconds: 10
                  timeoutSeconds: 1
                  failureThreshold: 3
              readiness: *probes
              startup:
                enabled: false

    env:
      TZ: ${TIMEZONE}
      PUID: 1000
      PGID: 1000

    service:
      main:
        ports:
          http:
            port: *port
    ingress:
      main:
        enabled: true
        className: {{ingress_type}}
        hosts:
          - host: &host "{{name}}.${SECRET_DOMAIN}"
            paths:
              - path: /
                pathType: Prefix
                service:
                  name: main
                  port: http
        tls:
          - hosts:
              - *host
    podSecurityContext:
      supplementalGroups:
        - 1000

    persistence:
      config:
        enabled: true
        mountPath: /config
        storageClass: longhorn
        size: 16Gi
        retain: true

      downloads:
        enabled: true
        mountPath: /downloads
        type: custom
        volumeSpec:
          nfs:
            server: "{{ media_nfs_host }}"
            path: "{{ media_nfs_downloads_path }}"

      tv:
        enabled: true
        mountPath: /tv
        type: custom
        volumeSpec:
          nfs:
            server: "{{ media_nfs_host }}"
            path: "{{ media_nfs_tv_path }}"

      tv2:
        enabled: true
        mountPath: /tv2
        type: custom
        volumeSpec:
          nfs:
            server: "{{ media_nfs_host }}"
            path: "{{ media_nfs_tv2_path }}"

    resources:
      requests:
        cpu: 15m
        memory: 335Mi
      limits:
        memory: 600Mi

    sidecars:
      exporter:
        image: ghcr.io/onedr0p/exportarr:v1.6.0
        args:
          - *app
        env:
          URL: http://localhost
          CONFIG: /config/config.xml
          PORT: &metrics-port 9794
          ENABLE_ADDITIONAL_METRICS: true
          ENABLE_UNKNOWN_QUEUE_ITEMS: true
          API_KEY: random-value-will-be-overriden-by-config-xml
        ports:
          - name: metrics
            containerPort: *metrics-port
        volumeMounts:
          - name: config
            mountPath: /config

"""
