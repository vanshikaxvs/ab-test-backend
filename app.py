"""
A/B Test Evaluation System — Full Backend
==========================================
A live Flask web app that:
  1. Tracks user visits and assigns them to Variant A or B (50/50 split)
  2. Records conversions (sign-ups / button clicks)
  3. Runs statistical analysis: z-test, confidence intervals, effect size, power analysis
  4. Tracks color preference per variant
  5. Exposes a REST API for the frontend dashboard

Run: python app.py
Dashboard: http://localhost:5000
"""

from flask import Flask, request, jsonify, render_template_string, make_response
from flask_cors import CORS
import sqlite3
import uuid
import json
import math
import time
import random
from datetime import datetime
from scipy import stats
import numpy as np

app = Flask(__name__)
CORS(app)
