These are deterministic test fixtures, not portfolio results or sample user data.

They were generated from eight explicitly chosen transactions using the unmodified
`prepare_sequential_input` and `run_sequential_policy` functions in
`alice-patrick/decision-centric-fraud-framework`, source commit
`b04585dc03ab4dad9b457969218a92fdca495cbe` (verified Main Framework source commit).
The fixture generation ran its original sequential engine and aggregation functions.

They cover a repeated entity, tied priority scores, capacity rejection, a step
without candidates, transaction types without alerts, and a completely empty
candidate audit. The fixtures are used only by the test suite and are never loaded
as dashboard reporting data.
