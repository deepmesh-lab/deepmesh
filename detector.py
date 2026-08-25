from __future__ import annotations

import os
import json
import pickle
import warnings
from dataclasses import dataclass
from typing import Optional

import numpy as np

try:
    from converter import FEAT_LEN, WIN_SIZE      # 단일 소스 — converter 와 항상 동일(표현 확장 시 자동 반영)
except Exception:
    FEAT_LEN, WIN_SIZE = 20, 5                     # 폴백(독립 실행 대비)

try:
    from sklearn.exceptions import InconsistentVersionWarning
    warnings.filterwarnings("ignore", category=InconsistentVersionWarning)
except Exception:
    pass

# 이 파일이 있는 곳 = 프로젝트 루트(서비스 디렉터리들의 부모)
ROOT = os.path.dirname(os.path.abspath(__file__))


@dataclass
class Verdict:
    session_id: int
    is_benign: bool
    score: float
    threshold: float


def _load_ocsvm(path: str):
    """ocsvm.pkl 로드. joblib 우선, 실패 시 pickle 폴백."""
    try:
        import joblib
        return joblib.load(path)
    except Exception:
        with open(path, "rb") as f:
            return pickle.load(f)


def _state_dict_report(sd) -> str:
    """state_dict 의 키/shape 요약(아키텍처 복원용 안내에 첨부)."""
    lines = []
    for k, v in list(sd.items())[:40]:
        shape = tuple(v.shape) if hasattr(v, "shape") else type(v).__name__
        lines.append(f"    {k}: {shape}")
    if len(sd) > 40:
        lines.append(f"    ... (총 {len(sd)}개 텐서)")
    return "\n".join(lines)


def _load_encoder(model_dir: str, arch: str, device: str, torch):
    """인코더 로드

      1) student_ts.pt 가 있으면 TorchScript 로 로드
      2) student.pth 가 TorchScript 로 저장된 경우
      3) student.pth 가 nn.Module 통째로 피클된 경우
      4) student.pth 가 state_dict 인 경우 → 아키텍처 정의가 필요하다.
         루트의 student_model.py 에서 build_student(arch=...) 를 찾아 쓴다.
         없으면 무엇이 필요한지 구체적으로 알리고 실패한다(임의 추정 금지).

    반환: (module, 로드경로설명)
    """
    ts_path = os.path.join(model_dir, "student_ts.pt")
    if os.path.isfile(ts_path):
        m = torch.jit.load(ts_path, map_location=device)
        m.eval()
        return m, "TorchScript(student_ts.pt)"

    pth_path = os.path.join(model_dir, "student.pth")
    if not os.path.isfile(pth_path):
        raise FileNotFoundError(f"인코더 가중치 없음: {pth_path} (또는 {ts_path})")

    try:
        obj = torch.load(pth_path, map_location=device, weights_only=False)
    except TypeError:                       # torch<2.0 은 weights_only 인자 없음
        obj = torch.load(pth_path, map_location=device)

    if isinstance(obj, torch.jit.ScriptModule):
        obj.eval()
        return obj, "TorchScript(student.pth)"

    if isinstance(obj, torch.nn.Module):
        obj.eval().to(device)
        return obj, "nn.Module 피클(student.pth)"

    sd = obj
    if isinstance(obj, dict):
        for key in ("state_dict", "model_state_dict", "student", "model"):
            if key in obj and isinstance(obj[key], dict):
                sd = obj[key]
                break

    builder = None
    try:
        import student_model
        builder = getattr(student_model, "build_student", None)
    except ImportError:
        pass

    if builder is None:
        raise RuntimeError(
            f"\n{pth_path} 는 TorchScript 가 아니라 state_dict 입니다.\n"
            f"현재 state_dict 의 키/shape:\n{_state_dict_report(sd)}\n"
        )

    model = builder(arch=arch)
    model.load_state_dict(sd)
    model.eval().to(device)
    return model, f"state_dict + student_model.build_student(arch={arch!r})"


class Detector:
    def __init__(self, service: str, models_root: Optional[str] = None,
                 device: str = "cpu", threshold_key: str = "threshold_df"):
        import torch
        self._torch = torch
        self.service = service
        self.device = device

        root = models_root if models_root is not None else ROOT
        # 새 규약: <root>/<svc>/<svc>_model/
        svc_dir = os.path.join(root, service, f"{service}_model")
        if not os.path.isdir(svc_dir):
            raise FileNotFoundError(
                f"model dir not found: {svc_dir}\n"
                f"  기대 구조: <root>/{service}/{service}_model/"
                f"{{student.pth, ocsvm.pkl, threshold.json, eval_results.json}}"
            )
        self.model_dir = svc_dir

        # 1) 인코더
        with open(os.path.join(svc_dir, "threshold.json"), encoding="utf-8") as f:
            thr_obj = json.load(f)
        self.encoder, self.encoder_source = _load_encoder(
            svc_dir, str(thr_obj.get("arch", "")), device, torch
        )

        # 2) OCSVM
        self.ocsvm = _load_ocsvm(os.path.join(svc_dir, "ocsvm.pkl"))

        # 3) 임계값(재보정본) — 판정에 쓰는 값
        self.threshold = float(thr_obj[threshold_key])
        self.meta = thr_obj

        # 4) 학습 시점 지표(참고용). 판정에 쓰지 않는다.
        self.eval_meta = {}
        ev_path = os.path.join(svc_dir, "eval_results.json")
        if os.path.isfile(ev_path):
            with open(ev_path, encoding="utf-8") as f:
                self.eval_meta = json.load(f)

        # 5) 정합성: threshold.json 의 vec_len 은 converter 의 FEAT_LEN 과 같아야 한다.
        vec_len = thr_obj.get("vec_len")
        if vec_len is not None and int(vec_len) != FEAT_LEN:
            raise ValueError(
                f"{service}: threshold.json vec_len={vec_len} != converter FEAT_LEN={FEAT_LEN}. "
                f"모델과 특징 길이가 어긋났습니다."
            )

    def embed(self, image: np.ndarray) -> np.ndarray:
        """(FEAT_LEN, WIN_SIZE) -> (1,128) 임베딩."""
        torch = self._torch
        if image.shape != (FEAT_LEN, WIN_SIZE):
            raise ValueError(f"expected image shape ({FEAT_LEN},{WIN_SIZE}), got {image.shape}")
        x = torch.from_numpy(np.ascontiguousarray(image, dtype=np.float32))[None, None]  # (1,1,FEAT_LEN,WIN_SIZE)
        with torch.no_grad():
            emb = self.encoder(x.to(self.device))
        return emb.detach().cpu().numpy()

    def score(self, image: np.ndarray) -> float:
        emb = self.embed(image)
        return float(self.ocsvm.decision_function(emb)[0])

    def detect(self, session_id: int, image: np.ndarray) -> Verdict:
        s = self.score(image)
        is_benign = (s >= self.threshold)                 # score < thr 이면 malicious
        return Verdict(session_id=session_id, is_benign=is_benign, score=s, threshold=self.threshold)