# evals/realrun/__init__.py
"""The real-model eval runner behind deploy/run-real-evals.sh (slice 10 A1).

estimate  what each suite will cost in rupees (cases × typical tokens × price × rate)
guard     the hard spending stop around every Claude call (1.5 × the estimate)
summary   each suite's report.json in plain English
runner    runs the chosen suites one by one under the guard
"""
