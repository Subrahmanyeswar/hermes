#!/usr/bin/env python3
"""
HERMES - Task Planner Tests
Tests: tool assignment, complexity scoring, permission levels,
       priority assignment, retry limits, and task uniqueness.

Run: pytest tests/test_planner.py -v
"""

import pytest

from core.planner import TaskPlanner, Task, PermissionLevel


def planner():
    return TaskPlanner()


# ──────────────────────────────────────────────────────────────────────
# Permission Level Tests
# ──────────────────────────────────────────────────────────────────────

def test_simple_read_task():
    task = planner().plan("Read the contents of app.py and show me")
    assert PermissionLevel.READ_ONLY == task.permission_level
    assert "read_file" in task.required_tools
    assert task.is_simple()


def test_write_task_gets_write_permission():
    task = planner().plan("Create a new file called hello.py with print hello")
    assert task.permission_level == PermissionLevel.WRITE
    assert "write_file" in task.required_tools


def test_execute_task_gets_execute_permission():
    task = planner().plan("Run the bash command to install dependencies")
    assert task.permission_level == PermissionLevel.EXECUTE
    assert "bash_exec" in task.required_tools


def test_git_push_gets_destructive_permission():
    task = planner().plan("Push the code to GitHub and publish it")
    assert task.permission_level == PermissionLevel.DESTRUCTIVE


def test_delete_gets_destructive_permission():
    task = planner().plan("Delete the old temp folder")
    assert task.permission_level == PermissionLevel.DESTRUCTIVE
    assert task.requires_confirmation() is True


# ──────────────────────────────────────────────────────────────────────
# Complexity Tests
# ──────────────────────────────────────────────────────────────────────

def test_complex_task_has_high_complexity():
    task = planner().plan(
        "Build a complete Flask REST API with user authentication, SQLite database, "
        "pytest tests, and JWT login including all routes and models"
    )
    assert task.complexity_score >= 0.6
    assert task.is_complex()


def test_simple_task_has_low_complexity():
    task = planner().plan("Just list the files in the current directory")
    assert task.complexity_score < 0.5


# ──────────────────────────────────────────────────────────────────────
# Priority & Retry Tests
# ──────────────────────────────────────────────────────────────────────

def test_urgent_task_gets_priority_1():
    task = planner().plan("Urgent: fix this bug in the login function immediately")
    assert task.priority == 1


def test_destructive_task_has_reduced_retries():
    task = planner().plan("Push to GitHub")
    assert task.max_retries == 1


# ──────────────────────────────────────────────────────────────────────
# Identity & Deduplication Tests
# ──────────────────────────────────────────────────────────────────────

def test_task_has_unique_id():
    p = planner()
    t1 = p.plan("task 1")
    t2 = p.plan("task 2")
    assert t1.task_id != t2.task_id


def test_required_tools_no_duplicates():
    task = planner().plan("Read and search for files and read the config")
    # read_file should only appear once even with multiple read keywords
    read_count = task.required_tools.count("read_file")
    assert read_count <= 1
