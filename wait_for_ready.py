#!/usr/bin/env python3
"""Wait for all selected Deployments and Pods using only the Kubernetes API."""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


SERVICE_ACCOUNT_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")
NAMESPACE = os.getenv("TARGET_NAMESPACE") or (
    SERVICE_ACCOUNT_DIR / "namespace"
).read_text(encoding="utf-8").strip()
SELECTOR = os.getenv("TARGET_SELECTOR", "app.kubernetes.io/instance=ai-gateway")
TIMEOUT_SECONDS = int(os.getenv("WAIT_TIMEOUT_SECONDS", "840"))
POLL_SECONDS = int(os.getenv("WAIT_POLL_SECONDS", "3"))

API_HOST = os.environ["KUBERNETES_SERVICE_HOST"]
API_PORT = os.getenv("KUBERNETES_SERVICE_PORT_HTTPS", "443")
API_ROOT = f"https://{API_HOST}:{API_PORT}"
TOKEN = (SERVICE_ACCOUNT_DIR / "token").read_text(encoding="utf-8").strip()
TLS_CONTEXT = ssl.create_default_context(cafile=str(SERVICE_ACCOUNT_DIR / "ca.crt"))


def api_get(path: str) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{API_ROOT}{path}",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    with urllib.request.urlopen(request, context=TLS_CONTEXT, timeout=10) as response:
        return json.load(response)


def list_resources(path: str) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"labelSelector": SELECTOR})
    response = api_get(f"{path}?{query}")
    return [
        item
        for item in response.get("items", [])
        if not item.get("metadata", {}).get("deletionTimestamp")
    ]


def deployment_status() -> tuple[bool, int, str]:
    deployments = list_resources(
        f"/apis/apps/v1/namespaces/{NAMESPACE}/deployments"
    )
    if not deployments:
        return False, 0, "matching Deployment가 아직 없음"

    expected_pods = 0
    for deployment in deployments:
        metadata = deployment.get("metadata", {})
        spec = deployment.get("spec", {})
        status = deployment.get("status", {})
        desired = int(spec.get("replicas", 1))
        expected_pods += desired
        name = metadata.get("name", "unknown")

        if int(status.get("observedGeneration", 0)) < int(metadata.get("generation", 0)):
            return False, expected_pods, f"Deployment/{name} 새 generation 관찰 대기"
        if int(status.get("updatedReplicas", 0)) < desired:
            return False, expected_pods, f"Deployment/{name} updatedReplicas 대기"
        if int(status.get("availableReplicas", 0)) < desired:
            return False, expected_pods, f"Deployment/{name} availableReplicas 대기"
        if int(status.get("unavailableReplicas", 0)) > 0:
            return False, expected_pods, f"Deployment/{name} unavailableReplicas 종료 대기"

    if expected_pods < 1:
        return False, expected_pods, "기대 Pod 수가 0"
    return True, expected_pods, f"Deployment {len(deployments)}개 Available"


def pod_status(expected_pods: int) -> tuple[bool, str]:
    pods = list_resources(f"/api/v1/namespaces/{NAMESPACE}/pods")
    if len(pods) < expected_pods:
        return False, f"Pod 생성 대기 ({len(pods)}/{expected_pods})"

    for pod in pods:
        metadata = pod.get("metadata", {})
        status = pod.get("status", {})
        name = metadata.get("name", "unknown")
        ready = any(
            condition.get("type") == "Ready" and condition.get("status") == "True"
            for condition in status.get("conditions", [])
        )
        if status.get("phase") != "Running" or not ready:
            return False, f"Pod/{name} Ready 대기"

    return True, f"Pod {len(pods)}개 Ready"


def main() -> None:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    stable_samples = 0
    last_message = ""

    print(f"대상 namespace={NAMESPACE} selector={SELECTOR}", flush=True)
    while time.monotonic() < deadline:
        try:
            deployments_ready, expected_pods, deployment_message = deployment_status()
            if deployments_ready:
                pods_ready, pod_message = pod_status(expected_pods)
                ready = pods_ready
                message = f"{deployment_message}; {pod_message}"
            else:
                ready = False
                message = deployment_message
        except (OSError, ValueError, urllib.error.URLError) as error:
            ready = False
            message = f"Kubernetes API 재시도: {error}"

        if message != last_message:
            print(message, flush=True)
            last_message = message

        # 순간적인 Ready 상태가 아니라 연속 두 번 확인된 상태만 통과시킨다.
        stable_samples = stable_samples + 1 if ready else 0
        if stable_samples >= 2:
            print("모든 대상 Deployment와 Pod가 Ready입니다.", flush=True)
            return
        time.sleep(POLL_SECONDS)

    raise TimeoutError(
        f"{TIMEOUT_SECONDS}초 안에 대상 Deployment와 Pod가 Ready가 되지 않았습니다"
    )


if __name__ == "__main__":
    main()

