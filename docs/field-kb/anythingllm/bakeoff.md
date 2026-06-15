# Model bake-off

Run this fixed question set against each candidate local model and score
the answers. Goal: pick the default LLM for the field laptops. Models
hot-swap in AnythingLLM without rebuilding the corpus.

## Questions (grounded — answers exist in the corpus)

1. Which Pi runs the DHCP server, and what is its IP address?
2. The SNAP shows no data. What do I check first?
3. How do I flash the Pico, and which Pi do I do it from?
4. What does `casperfpga` do and which role requires it?
5. Where is the RFSoC bitstream stored and how does it get to the RFSoC?
6. What are the Redis buses used for?
7. `cmtvna.service` won't start — walk me through it.
8. What does `eigsep-field doctor` check?
9. What is the difference between the panda and backend roles?
10. How do I revert the Pico to the blessed firmware?

## Scoring

Give each answer one composite 1–5 score (5 = grounded in the corpus,
correct, cites a doc, and concise). Put the per-question score in the
cell; use Notes for anything notable.

| Model | Q1 | Q2 | Q3 | Q4 | Q5 | Q6 | Q7 | Q8 | Q9 | Q10 | Notes |
|-------|----|----|----|----|----|----|----|----|----|-----|-------|
| qwen2.5:7b-instruct  |  |  |  |  |  |  |  |  |  |  | |
| (other candidate)    |  |  |  |  |  |  |  |  |  |  | |

Record the laptop's RAM/GPU and the model's tokens/sec so the choice is
reproducible.
