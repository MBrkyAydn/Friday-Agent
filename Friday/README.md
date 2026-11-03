# FRIDAY

Autonomous AI Coding & Workflow Automation CLI.

## Overview
FRIDAY is an autonomous developer CLI agent designed to inspect, edit, test, and verify code inside an isolated workspace.

## Installation
```bash
pip install -e .
```

## Usage
Interactive REPL in current directory:
```bash
friday
```

Execute a single instruction:
```bash
friday -p "Refactor authentication module"
```

Or target a specific project workspace:
```bash
friday run /path/to/project --prompt "Run tests and fix failures"
```
