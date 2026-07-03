import numpy as np, json
X = np.load('deepmesh-temp-ai/model-training/data/auth-service/X_benign.npy')
print("shape:", X.shape)          # 기대: (N, 1479, 5),  N>0
print("dtype/range:", X.dtype, float(X.min()), float(X.max()))  # 0.0~1.0
print("non-zero ratio:", float((X>0).mean()))   # 패딩 정도 (작을수록 패딩 많음)
print(open('deepmesh-temp-ai/model-training/data/auth-service/stats.json').read())