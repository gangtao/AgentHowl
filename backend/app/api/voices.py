"""描述声线试听（issue #103 跟进）：按描述生成锚点音频并返回可播放 URL；档案保存 anchor id 后，
对局里每句都以它为参考克隆，音色一致。锚点是公开的声音样本（不含对局信息），读取不鉴权。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.agent.profile import MAX_VOICE_STYLE_CHARS
from app.runtime.tts import TtsClient, TtsError
from app.runtime.voice_anchors import VoiceAnchorStore

router = APIRouter(prefix="/voices", tags=["voices"])


class DesignRequest(BaseModel):
    style: str = Field(min_length=1, max_length=MAX_VOICE_STYLE_CHARS)


class DesignResponse(BaseModel):
    anchor_id: str
    url: str


def get_anchors(request: Request) -> VoiceAnchorStore:
    store: VoiceAnchorStore = request.app.state.voice_anchors
    return store


@router.post("/design")
async def design_voice(req: DesignRequest, request: Request) -> DesignResponse:
    """生成一个新锚点（每次调用都是重新设计：不满意就再点一次）。TTS 不可用 → 503。"""
    tts: TtsClient = request.app.state.tts
    style = req.style.strip()
    if not style:
        raise HTTPException(status_code=422, detail="声线描述不能为空")
    try:
        wav = await tts.design_anchor(style)
    except TtsError as exc:
        raise HTTPException(status_code=503, detail=f"TTS 服务不可用：{exc}") from exc
    anchor_id = get_anchors(request).put(wav)
    return DesignResponse(anchor_id=anchor_id, url=f"/api/v1/voices/{anchor_id}")


@router.get("/{anchor_id}")
def fetch_voice(anchor_id: str, request: Request) -> FileResponse:
    try:
        path = get_anchors(request).path_for(anchor_id)
    except ValueError:
        path = None  # 非法 id 与不存在同样 404
    if path is None:
        raise HTTPException(status_code=404, detail="声线样本不存在")
    return FileResponse(
        path,
        media_type="audio/wav",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
