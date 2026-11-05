import json
import subprocess
from typing import Protocol

from broker.src.injector.events import PodSpec


class Runner(Protocol):
    def apply(self, cluster: str, manifest: dict) -> None: ...
    def delete(self, cluster: str, namespace: str, name: str) -> None: ...


def pod_manifest(spec: PodSpec) -> dict:
    annotations: dict[str, str] = {}
    if spec.cpu_usage_m is not None:
        annotations["kwok.x-k8s.io/usage-cpu"] = f"{spec.cpu_usage_m}m"
    if spec.memory_usage_mi is not None:
        annotations["kwok.x-k8s.io/usage-memory"] = f"{spec.memory_usage_mi}Mi"
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": spec.name,
            "namespace": spec.namespace,
            "annotations": annotations,
        },
        "spec": {
            "containers": [
                {
                    "name": "app",
                    "image": "nginx",
                    "resources": {
                        "requests": {
                            "cpu": f"{spec.cpu_request_m}m",
                            "memory": f"{spec.memory_request_mi}Mi",
                        }
                    },
                }
            ]
        },
    }


def _kubectl(cluster: str, args: list[str], stdin: str | None = None) -> None:
    command = ["kubectl", "--context", f"kwok-{cluster}", *args]
    result = subprocess.run(command, input=stdin, text=True, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"kubectl exited with {result.returncode}")


class KubectlRunner:
    def apply(self, cluster: str, manifest: dict) -> None:
        _kubectl(cluster, ["apply", "-f", "-"], json.dumps(manifest))

    def delete(self, cluster: str, namespace: str, name: str) -> None:
        _kubectl(
            cluster,
            ["delete", "pod", name, "-n", namespace, "--ignore-not-found", "--wait=false"],
        )