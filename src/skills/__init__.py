"""skills package — re-exports all skill classes."""
from skills.base import SkillBase, SkillResult  # noqa: F401
from skills.system_architect import SystemArchitectSkill  # noqa: F401
from skills.knowledge_synthesizer import KnowledgeSynthesizerSkill  # noqa: F401
from skills.technical_proposal_generator import TechnicalProposalGeneratorSkill  # noqa: F401
from skills.data_repurposer import DataRepurposerSkill  # noqa: F401
from skills.sandbox_guard import SandboxGuardSkill  # noqa: F401
from skills.system_pulse import SystemPulseSkill  # noqa: F401
from skills.research_summarizer import ResearchSummarizerSkill  # noqa: F401
from skills.file_writer import FileWriterSkill  # noqa: F401
from skills.fallback import FallbackSkill  # noqa: F401


def get_all_skills() -> list[SkillBase]:
    """Return one instance of every registered skill (excluding FallbackSkill)."""
    return [
        SystemArchitectSkill(),
        KnowledgeSynthesizerSkill(),
        TechnicalProposalGeneratorSkill(),
        DataRepurposerSkill(),
        SandboxGuardSkill(),
        SystemPulseSkill(),
        ResearchSummarizerSkill(),
        FileWriterSkill(),
    ]
