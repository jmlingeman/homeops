REPO="$(git rev-parse --show-toplevel)" || exit 1
rm -rf "$REPO/kubernetes" && task configure && git add "$REPO" && git commit -a -m "$1" && git push
