# PP-MAP Public Lab

Public, isolated research/workbench for the PocketPVP map-generation pipeline.

This repository intentionally contains only PP-MAP research fixtures and proof code. The private game repository is not mirrored here.

## Current public gate

`PP-MAP-PUBLIC-COMPOUND-SMOKE-V1` reproduces the first lawful place-level compound from two canonical retained fixtures:

- dogleg generalized-world OTBM: SHA-256 `93b3da81bc799404a0d81d0d9b09b754c676c0f646c6e07eb7e3b2259758150d`
- accepted fixed 3x3 whole-building OTBM: SHA-256 `20ec5cb88db4b19c7b7d25e47f7e6102073d9dd3cac8643bfbd0a7039bbd95e2`

Expected compound:

- 12,476 bytes
- 1,435 tiles
- SHA-256 `209f82e6e8b2829c0aa98fa351a870ab024a5fcfddca04758623b299e11a9677`
- 101 changed tiles
- zero changes outside the replaced host lower/upper envelope
- host 101-105 grass variation preserved exactly
- fixed 3x3 modules remain unresized and roofs remain separate

## Why this repo exists

The private repository's recent GitHub Actions jobs repeatedly received `runner_id=0` and executed zero steps. This public lab removes private-artifact dependencies and uses committed canonical fixtures so public Actions can execute the PP-MAP proofs directly.

Production status remains **UNCLASSIFIED**.
