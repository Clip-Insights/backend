#!/usr/bin/env python
"""Run: cd backend && python scripts/integration_smoke.py"""
import os
import sys

os.environ.setdefault("LLM_PROVIDER", "noop")
os.environ.setdefault("EMAIL_PROVIDER", "console")
os.environ.setdefault("ANALYTICS_PROVIDER", "noop")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from integrations.registry import get_llm, get_email, get_analytics


def main():
    assert get_llm().complete("test") == "[noop llm response]"
    chunks = list(get_llm().stream("test"))
    assert chunks == ["[noop llm response]"]

    get_email().send("a@b.c", "subj", "body")
    get_analytics().fetch_and_store()

    print("integration_smoke: PASS")


if __name__ == "__main__":
    main()
