#!/bin/bash
set -e

cd /root/bot

# Install bot dependencies (including SC2MapAnalysis extension)
uv pip install --system -e .

# Build the mapanalyzerext C extension for Linux
cd /root/bot/MapAnalyzer/cext/src
gcc -O2 -shared -fPIC -o /root/bot/MapAnalyzer/cext/mapanalyzerext.so \
    -I$(python3 -c "import numpy; print(numpy.get_include())") \
    -I$(python3 -c "import sysconfig; print(sysconfig.get_path('include'))") \
    ma_ext.c

cd /root/bot
python run.py "$@"
