"""The one interpreter launch a hook costs.

The wrapper used to launch Python twice per hook: once to ask whether it
was 3.10+, once to run the script. On a machine where every process start
takes seconds - endpoint security scanning each executable - that second
launch alone pushed the UserPromptSubmit hook past its 10s budget, and a
hook past its budget is discarded with its check. Here the version check
and the script share one launch.

Exit 113 means "this interpreter is too old". The wrapper then tries the
next candidate. No hook script exits 113 on its own, so the wrapper never
mistakes a hook's result for a rejected interpreter.

Everything above the version check has to parse on any Python, old ones
included - that is the whole reason the check is a file and not a line
in the script it protects.
"""
import sys

if sys.version_info < (3, 10):
    sys.exit(113)

import runpy  # noqa: E402

sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name="__main__")
