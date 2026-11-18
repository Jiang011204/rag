FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

# torch 装 CPU 版：用 --find-links 让 pip 自行到阿里云 pytorch-wheels 解析。
# 切勿手动拼 wheel 的 URL —— 版本号随上游变动（此前拼 2.6.0 只换回一张 HTML 错误页）。
# 走 CPU 版可避开 PyPI 上捆绑 CUDA 的发行版（会额外拖来 2.7GB 用不上的 nvidia-* 库）。
# 本层内容长期不变，可稳定命中 Docker 构建缓存，改业务依赖不必重下 torch。
RUN pip install --no-cache-dir \
    --index-url https://mirrors.aliyun.com/pypi/simple/ \
    --find-links https://mirrors.aliyun.com/pytorch-wheels/cpu \
    torch

# 业务依赖独立成层：torch 已就位，sentence-transformers 会直接复用，不会重装。
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt

COPY . .

EXPOSE 8000 8501

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
