# 
$dir = "AGENT-work-logs"
New-Item -ItemType Directory -Force -Path $dir | Out-Null

git status --short | Out-File "$dir/latest-status.txt" -Encoding utf8
git diff --name-status | Out-File "$dir/changed-files.txt" -Encoding utf8
git diff | Out-File "$dir/latest-diff.patch" -Encoding utf8
git diff --cached | Out-File "$dir/staged-diff.patch" -Encoding utf8
git branch --show-current | Out-File "$dir/current-branch.txt" -Encoding utf8
git rev-parse HEAD | Out-File "$dir/base-commit.txt" -Encoding utf8

"Updated at: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Out-File "$dir/generated-at.txt" -Encoding utf8