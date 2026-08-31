# Templates 없는 AI Gateway post-deploy 예제

기존 배포 파일 네 개와 post-deploy용 파일 세 개를 사용한다.

```text
Chart.yaml
values.yaml
secrets.yaml
kustomization.yaml
post-deploy.yaml   # Ready 대기 Job과 RBAC
wait_for_ready.py  # Kubernetes API 기반 Ready 확인
run.sh             # 실제 실행할 별도 스크립트
```

`Chart.yaml`은 GitLab AI Gateway를 dependency로 사용하므로 로컬 `templates/`가 필요 없다. 기존 `kustomization.yaml`에서는 `post-deploy.yaml`을 리소스로 추가하고 `configMapGenerator`가 별도 `wait_for_ready.py`와 `run.sh`를 ConfigMap으로 변환한다. `Chart.yaml`의 dependency URL도 실제 폐쇄망 내부 Helm repository 주소로 바꿔야 한다.

폐쇄망을 위해 post-deploy Job은 `kubectl`이나 `alpine` 이미지를 사용하지 않는다. AI Gateway와 똑같이 사내에 미러링된 이미지를 재사용하고, 그 이미지에 포함된 Python 표준 라이브러리로 Kubernetes API를 조회한다. `values.yaml`의 `ai-gateway.image`와 `post-deploy.yaml`의 Job image를 반드시 같은 repository/tag로 설정한다.

이 예제의 `secrets.yaml`은 Kubernetes `Secret` manifest라 `resources`에 포함했다. 실제 `secrets.yaml`이 Helm values 파일이라면 기존 Helm 처리 방식을 유지하고, `kustomization.yaml`에는 `post-deploy.yaml`만 추가해야 한다.

## 배포

기존 Secret/Kustomize 적용 단계와 Helm 배포 단계를 그대로 사용한다. 아래는 이 예제를 그대로 실행하는 순서다.

```bash
# Namespace 및 Secret을 먼저 준비한다. post-deploy Job도 함께 생성되지만,
# wait_for_ready.py가 AI Gateway Deployment와 Pod가 Ready 될 때까지 기다린다.
kubectl create namespace ai-gateway --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -k .

# templates/가 아니라 dependency chart를 설치한다.
helm dependency update .
helm upgrade --install ai-gateway . \
  --namespace ai-gateway \
  --values values.yaml \
  --wait \
  --wait-for-jobs \
  --timeout 15m

# post-deploy 스크립트 완료 확인
kubectl wait job/ai-gateway-post-deploy \
  --namespace ai-gateway \
  --for condition=Complete \
  --timeout 15m
```

실제 명령은 별도 [`run.sh`](run.sh)에 작성한다. Kustomize가 `run.sh`와 `wait_for_ready.py`를 `ai-gateway-post-deploy-script` ConfigMap으로 만든다. 스크립트에 필요한 비밀 값은 `secrets.yaml` 같은 기존 Secret에서 `envFrom` 또는 Secret volume으로 주입한다.

AI Gateway 릴리스 이름이 `ai-gateway`가 아니면 `post-deploy.yaml`의 selector도 바꿔야 한다.

```yaml
- name: TARGET_SELECTOR
  value: app.kubernetes.io/instance=<실제-Helm-release-name>
```

## 상태와 로그

```bash
kubectl get deployments,pods,jobs -n ai-gateway

POST_DEPLOY_POD=$(kubectl get pods -n ai-gateway \
  -l job-name=ai-gateway-post-deploy \
  --field-selector=status.phase=Succeeded \
  -o jsonpath='{.items[0].metadata.name}')

kubectl logs -n ai-gateway "$POST_DEPLOY_POD" -c run-script
```

## 다시 실행

완료된 Kubernetes Job은 `kubectl apply`만으로 다시 실행되지 않는다. 스크립트를 다시 실행해야 할 때 Job만 삭제하고 Kustomize를 다시 적용한다.

```bash
kubectl delete job ai-gateway-post-deploy -n ai-gateway --ignore-not-found
kubectl apply -k .
kubectl wait job/ai-gateway-post-deploy -n ai-gateway \
  --for condition=Complete --timeout 15m
```

## 정리

```bash
kubectl delete -k . --ignore-not-found
helm uninstall ai-gateway -n ai-gateway --ignore-not-found

# namespace를 이 배포만 사용하는 것이 확실할 때만 실행
kubectl delete namespace ai-gateway
```
