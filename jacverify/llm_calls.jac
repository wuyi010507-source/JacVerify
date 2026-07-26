"""Small, typed byLLM calls for the FIFO verification demo."""


obj FifoFailureContext {
    has module_name: str,
        requirements: list[str],
        failure_kind: str,
        expected: str,
        observed: str,
        cycle: str,
        tool_output: str;
}

sem FifoFailureContext = """
Evidence from one reproducible FIFO verification failure. Tool output is
authoritative; the model must not invent a simulator result.
""";
sem FifoFailureContext.requirements = "Relevant FIFO requirements from the checked-in specification.";
sem FifoFailureContext.failure_kind = "Normalized failure category emitted by the testbench.";
sem FifoFailureContext.expected = "Expected value reported by the testbench.";
sem FifoFailureContext.observed = "Observed value reported by the testbench.";
sem FifoFailureContext.cycle = "Failure cycle when available, otherwise an empty string.";
sem FifoFailureContext.tool_output = "Raw simulator output associated with this failure.";


obj RankedHypothesisOutput {
    has rank: int,
        claim: str,
        confidence: float,
        next_action: str;
}

sem RankedHypothesisOutput.rank = "Unique rank starting at 1; lower is more likely.";
sem RankedHypothesisOutput.claim = "One concrete, falsifiable RTL root-cause hypothesis.";
sem RankedHypothesisOutput.confidence = "Relative confidence from 0.0 to 1.0.";
sem RankedHypothesisOutput.next_action = "One minimal inspection or targeted verification action.";


obj HypothesisRankingOutput {
    has hypotheses: list[RankedHypothesisOutput];
}

sem HypothesisRankingOutput.hypotheses = """
Exactly three distinct hypotheses ordered from most likely to least likely.
""";


obj ArtifactProposalOutput {
    has kind: str,
        description: str,
        verification_goal: str,
        rationale: str;
}

sem ArtifactProposalOutput.kind = """
One of: directed_test, sva_assertion, or reviewed_rtl_candidate.
""";
sem ArtifactProposalOutput.description = "Short description of the smallest useful artifact.";
sem ArtifactProposalOutput.verification_goal = "The exact behavior the simulator should check.";
sem ArtifactProposalOutput.rationale = "Why this artifact discriminates the selected hypothesis.";


def rank_fifo_failure(
    context: FifoFailureContext
) -> HypothesisRankingOutput by llm();

sem rank_fifo_failure = """
Act as a conservative RTL verification engineer. Diagnose only from the
provided FIFO requirements and simulator evidence. Return exactly three
distinct, falsifiable hypotheses, ordered by likelihood. Keep confidence in
[0, 1], make rank values 1, 2, and 3, and make every next_action small and
executable. Never claim that the design passes, never fabricate coverage or
waveform facts, and do not propose a broad rewrite.
""";


def propose_fifo_artifact(
    context: FifoFailureContext,
    top_hypothesis: RankedHypothesisOutput
) -> ArtifactProposalOutput by llm();

sem propose_fifo_artifact = """
Propose one minimal verification artifact for the selected FIFO hypothesis.
Prefer a directed wraparound test or focused assertion. A reviewed RTL
candidate is allowed only as a proposal for simulator re-verification. Do not
return file paths, shell commands, PASS/FAIL verdicts, or unbounded code. The
simulator, not the model, owns the final verdict.
""";
