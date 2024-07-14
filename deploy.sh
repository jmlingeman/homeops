 rm -rf ~/Workspace/homeops/kubernetes && task configure && git add `git rev-parse --show-toplevel` && git commit -a -m "$1" && git push
