2026.07.15 安装了 3.13.14


1. 下载 micromamba 本体，放到项目根目录

https://github.com/mamba-org/micromamba-releases/releases/download/2.8.1-0/micromamba-win-64.exe


2. 运行指令创建 python 环境

.\micromamba-win-64.exe create -y --prefix "$PWD\python" --root-prefix "$PWD\.mamba" --override-channels --channel https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge python=3.13

这是单行指令，运行前需要先 cd 到 root

解释
--prefix: 指定 python 环境的绝对安装路径
--root-prefix: 指令 mamba 自身的根目录 (放下载缓存、mantadata等)
--override-channels: 禁用所有默认 channel 只走清华源
--channel: 指定从清华源下载
python=3.13: 安装 python 3.13 本体


3. 后处理

运行完毕后, 应该会出现 .mamba/ 和 python/ 两个文件夹

删除 .mamba/ 和 micromamba-win-64.exe 本体
删除 python/conda-meta/ 这个文件夹

将本文档同位置的 sitecustomize.py 放入 pytohn/ 内

然后将整个 python 文件夹打包成 zip 放到 for_release_only 内
