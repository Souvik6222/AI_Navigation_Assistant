# Task Tracker

## Group 1: Hallucination Fixes
- [ ] Fix depth normalisation in `depth_estimator.py` (rolling percentile range)
- [ ] Upgrade tracker to Hungarian algorithm + motion prediction in `tracker.py`
- [ ] Move numpy import to top-level in `tracker.py`

## Group 2: Latency Fixes
- [ ] Fix pyttsx3 re-init in `voice.py` (reuse engine, platform check)
- [ ] Replace gTTS with offline Hindi TTS in `voice.py`
- [ ] Increase default resolution in `config.yaml`

## Group 3: Critical Issues
- [ ] Unify distance thresholds in `main.py` (CRIT-2)
- [ ] Unify distance thresholds in `server.py` (CRIT-2)
- [ ] Rename claude_client → llm_client (CRIT-3)
- [ ] Update all imports/references for rename

## Group 4: Major Issues
- [ ] Add rate limiting + retry for Groq API in `llm_client.py` (MAJ-1)

## Group 5: Significant Issues
- [ ] Add path clearance announcements in `decision_engine.py` (SIG-2)
- [ ] Add velocity estimation in `tracker.py` (SIG-3)
- [ ] Add velocity-based alert escalation in `decision_engine.py` (SIG-3)
