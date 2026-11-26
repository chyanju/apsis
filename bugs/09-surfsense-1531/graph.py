# Derived from SurfSense (github.com/MODSetter/SurfSense, Apache-2.0) and modified; license text in LICENSE.

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph
from pydantic import BaseModel, Field


class SlideContent(BaseModel):
    slide_number: int = Field(..., description="1-based slide number")
    title: str = Field(..., description="Concise slide title")
    subtitle: str = Field(..., description="One-line subtitle or tagline")
    content_in_markdown: str = Field(..., description="Slide body content formatted as markdown")
    speaker_transcripts: list[str] = Field(..., description="2-4 short sentences a presenter would say while this slide is shown")
    background_explanation: str = Field(..., description="Emotional mood and color direction for this slide")


class SlideAudioResult(BaseModel):
    slide_number: int
    audio_file: str = Field(..., description="Path to the per-slide audio file")
    duration_seconds: float = Field(..., description="Audio duration in seconds")
    duration_in_frames: int = Field(..., description="Audio duration in frames (at 30fps)")


class SlideSceneCode(BaseModel):
    slide_number: int
    code: str = Field(..., description="Raw Remotion React component source code for this slide")
    title: str = Field(..., description="Short title for the composition")


@dataclass
class State:
    db_session: Any
    source_content: str

    slides: list[SlideContent] | None = None
    slide_audio_results: list[SlideAudioResult] | None = None
    slide_theme_assignments: dict[int, tuple[str, str]] | None = None
    slide_scene_codes: list[SlideSceneCode] | None = None


@dataclass(kw_only=True)
class Configuration:
    video_title: str
    search_space_id: int
    user_prompt: str | None = None

    @classmethod
    def from_runnable_config(cls, config: RunnableConfig | None = None) -> Configuration:
        configurable = (config.get("configurable") or {}) if config else {}
        _fields = {f.name for f in fields(cls) if f.init}
        return cls(**{k: v for k, v in configurable.items() if k in _fields})


async def create_presentation_slides(state: State, config: RunnableConfig) -> dict[str, Any]:
    slides: list[SlideContent] = []
    return {"slides": slides}


async def create_slide_audio(state: State, config: RunnableConfig) -> dict[str, Any]:
    audio_results_sorted = [
        SlideAudioResult(slide_number=slide.slide_number, audio_file="", duration_seconds=0.0, duration_in_frames=0)
        for slide in state.slides or []
    ]
    return {"slide_audio_results": audio_results_sorted}


async def assign_slide_themes(state: State, config: RunnableConfig) -> dict[str, Any]:
    assignments = {slide.slide_number: ("default", "light") for slide in state.slides or []}
    return {"slide_theme_assignments": assignments}


async def generate_slide_scene_codes(state: State, config: RunnableConfig) -> dict[str, Any]:
    scene_codes = [
        SlideSceneCode(slide_number=audio.slide_number, code="", title="")
        for audio in state.slide_audio_results or []
        if audio.slide_number in (state.slide_theme_assignments or {})
    ]
    return {"slide_scene_codes": scene_codes}


def build_graph():
    workflow = StateGraph(State, config_schema=Configuration)

    workflow.add_node("create_presentation_slides", create_presentation_slides)
    workflow.add_node("create_slide_audio", create_slide_audio)
    workflow.add_node("assign_slide_themes", assign_slide_themes)
    workflow.add_node("generate_slide_scene_codes", generate_slide_scene_codes)

    # Fan-out: after slides are parsed, run audio generation and theme
    # assignment in parallel (themes only need slide metadata, not audio).
    workflow.add_edge("__start__", "create_presentation_slides")
    workflow.add_edge("create_presentation_slides", "create_slide_audio")
    workflow.add_edge("create_presentation_slides", "assign_slide_themes")

    # Fan-in: scene code generation waits for both audio and themes.
    workflow.add_edge("create_slide_audio", "generate_slide_scene_codes")
    workflow.add_edge("assign_slide_themes", "generate_slide_scene_codes")

    workflow.add_edge("generate_slide_scene_codes", "__end__")

    graph = workflow.compile()
    graph.name = "Surfsense Video Presentation"

    return graph


graph = build_graph()
