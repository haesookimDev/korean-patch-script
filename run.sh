#!/bin/sh
set -eu

# 이 파일에 실제 실행할 스크립트를 작성한다.
echo "POST_DEPLOY_STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "AI Gateway의 Deployment와 Pod가 모두 Ready 상태입니다."

# Secret 사용 예시. 실제 값을 로그에 출력하지 않는다.
test -n "${EXAMPLE_TOKEN:-}"
