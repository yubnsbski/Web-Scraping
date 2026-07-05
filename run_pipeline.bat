@echo off
set WS=C:\Users\ynobe\Documents\GitHub\Web-Scraping
set LOG=%WS%\pipeline_log.txt
echo PIPELINE START > "%LOG%"
echo Step 1: jpx_ml_v2.py >> "%LOG%"
py -3.11 "%WS%\jpx_ml_v2.py" >> "%LOG%" 2>&1
echo Step 2: jpx_ml_v3.py (yfinance fetch ~10min) >> "%LOG%"
py -3.11 "%WS%\jpx_ml_v3.py" >> "%LOG%" 2>&1
echo Step 3: jpx_viz_gen.py >> "%LOG%"
py -3.11 "%WS%\jpx_viz_gen.py" >> "%LOG%" 2>&1
echo PIPELINE DONE >> "%LOG%"
