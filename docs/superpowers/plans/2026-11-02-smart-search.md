# 智能视频检索 v4.4.0 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 AI 视频配音 Pro 上新增独立「🔍 智能检索」窗口，支持批量视频 + HN/V2EX 热点 + LLM/关键词匹配 + 片段导出，且不改变主配音流程。

**Architecture:** 新增 `core/search_types.py`（共享 dataclass）、`core/smart_search.py`（零 Qt 检索逻辑）、`core/trend_sources.py`（零 Qt 热点抓取）、`core/trend_thread.py` 与 `core/search_thread.py`（QThread）、`ui/smart_search_dialog.py`（独立模态窗口）。主界面只加一个按钮和懒加载入口。

**Tech Stack:** Python 3.12、PyQt5、ffmpeg/ffprobe、Whisper、OpenAI 兼容客户端、requests、xml.etree、pytest。

**Spec:** `智能视频检索v4.4.0设计方案20261102.md`

---

## Global Constraints

- 当前分支必须是 `feature/v4.4.0-smart-search`；基线提交 `abff400`，标签 `v4.3.4-baseline`。
- **禁止修改**：`core/process_thread.py`、`core/video_processor.py`、`core/audio_pipeline.py`、`core/llm_config.py`、`ui/api_config_dialog.py`。
- 检索时间戳只能来自 Whisper `result["segments"]`（未压缩）；**禁止**调用 `_compress_silence()`，**禁止**复用 `subtitles_timeline`。
- 不引入新第三方依赖；网络用 `requests`，RSS 用 `xml.etree.ElementTree`，哈希用 `hashlib`。
- 所有阈值常量集中在 `core/smart_search.py` 顶部：`PREFILTER_THRESHOLD=0.12`、`PREFILTER_MIN_CANDIDATES=20`、`PREFILTER_MIN_RATIO=0.05`、`LLM_CONFIDENCE_HIT=0.5`、`LLM_CONFIDENCE_MAYBE=0.35`、`KEYWORD_HIT_SCORE=0.3`、`LLM_TIMEOUT_SECONDS=30`、`LLM_MAX_CONSECUTIVE_FAILURES=2`、`DEFAULT_BATCH_SIZE=10`。
- 新功能必须可通过 `ENABLE_SMART_SEARCH` / `AI_VIDEO_SMART_SEARCH=0` 关闭；`ui/ui_main.py` 只允许新增按钮、`open_smart_search()`、开关判断。
- 每个任务结束必须跑对应测试；提交信息遵循 Conventional Commits，并以 `Co-Authored-By: Claude Code <noreply@anthropic.com>` 结尾。
- 基线测试：`python3 -m pytest tests/ -q` 应为 64 passed + 1 skipped；不得让已有测试失败或新增 skip。

## Review Focus

以下 5 类输入/故障最容易被实现者忽略，且一旦出错会直接影响用户：

1. **中文 query 匹配英文转写**：预筛不能把句子全部滤掉；预筛候选过少或无 token 交集时必须回退全量。由 Task 1 的 `test_prefilter_falls_back_for_cross_language` 锁定。
2. **无音轨视频**：提音频与导出都必须能处理没有音频流的视频。由 Task 4 的 `test_extract_audio_builds_ffmpeg_command` 与 Task 6 的 `-map 0:a:0?` 断言锁定。
3. **批量中单个视频损坏**：不能中断整批。由 Task 10 的 `test_thread_continues_after_file_failure` 锁定。
4. **LLM 不可达 / 返回非法 JSON**：必须熔断并回退关键词，不能逐句超时。由 Task 5 的 `test_llm_match_circuit_breaker` 和 Task 10 的 `test_thread_uses_keyword_fallback_when_llm_unavailable` 锁定。
5. **递归批量同名文件**：导出文件名不能互相覆盖。由 Task 6 的 `test_build_clip_filename_includes_filekey` 锁定。

---

## File Structure

| 文件 | 职责 |
|------|------|
| `core/search_types.py` | 共享 dataclass，零依赖，避免循环导入 |
| `core/smart_search.py` | 分词/匹配/预筛/合并/转写/缓存/LLM/导出/报告/去重台账 |
| `core/trend_sources.py` | HN/V2EX 抓取、解析、缓存、关键词、自动归纳 |
| `core/trend_thread.py` | `TrendFetchThread(QThread)` 异步抓取 |
| `core/search_thread.py` | `SmartSearchThread(QThread)` 编排全流程 |
| `ui/smart_search_dialog.py` | 独立模态对话框 |
| `ui/ui_main.py` | +按钮、+懒加载入口、+开关 |
| `core/config.py` | +`ENABLE_SMART_SEARCH` |
| `AI视频配音Pro.spec` | +6 个 hiddenimports |
| `tests/test_smart_search.py` | 检索核心单测 |
| `tests/test_trend_sources.py` | 热点 + TrendFetchThread 单测 |
| `tests/test_search_thread.py` | SmartSearchThread 编排单测 |

---

### Task 1: 共享类型 + 分词/关键词匹配/预筛

**Files:**
- Create: `core/search_types.py`
- Create: `core/smart_search.py`
- Create: `tests/test_smart_search.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `SearchIndex(source_file: str, filekey8: str, duration: float, segments: list[dict])`
  - `Hit(index: int, score: float, reason: str = "", angles: list[str] = field(default_factory=list))`
  - `Clip(source_file, filekey8, start, end, matched_sentences, score, reason, angles, clip_path="", already_exported=False)`
  - `MatchContext(query: str, angles: list[TrendAngle])`
  - `Hotspot(source, title, url, score=0, comments=0, keywords=[])`
  - `TrendAngle(title, keywords, why, source_ids=[])`
  - `build_index(segments: list[dict], source_file: str, filekey8: str, duration: float) -> SearchIndex`
  - `tokenize(text: str) -> list[str]`
  - `keyword_match(context: MatchContext, index: SearchIndex) -> list[Hit]`
  - `prefilter(context: MatchContext, index: SearchIndex, threshold: float = PREFILTER_THRESHOLD) -> list[int]`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_smart_search.py
from core.search_types import Hit, MatchContext, SearchIndex, TrendAngle
from core.smart_search import keyword_match, prefilter, tokenize


def _index(texts, duration=60.0):
    segments = [
        {"start": i * 3.0, "end": i * 3.0 + 2.0, "text": t}
        for i, t in enumerate(texts)
    ]
    return SearchIndex(
        source_file="demo.mp4", filekey8="abcd1234",
        duration=duration, segments=segments,
    )


def test_tokenize_cjk_bigrams():
    tokens = tokenize("价格是多少")
    assert "价格" in tokens
    assert "格是" in tokens
    assert "多少" in tokens


def test_tokenize_mixed_latin_and_cjk():
    tokens = tokenize("Hello 价格 world")
    assert "hello" in tokens
    assert "world" in tokens
    assert "价格" in tokens


def test_keyword_match_hits_relevant_sentence():
    ctx = MatchContext(query="价格", angles=[])
    hits = keyword_match(ctx, _index(["这个价格很便宜", "今天天气不错"]))
    assert len(hits) == 1
    assert hits[0].index == 0
    assert hits[0].score >= 0.3


def test_keyword_match_records_angle():
    ctx = MatchContext(
        query="",
        angles=[TrendAngle(title="成本", keywords=["价格"], why="")],
    )
    hits = keyword_match(ctx, _index(["这个价格很便宜"]))
    assert hits[0].angles == ["成本"]


def test_prefilter_falls_back_for_cross_language():
    ctx = MatchContext(query="价格", angles=[])
    idx = _index([f"english sentence number {i}" for i in range(30)])
    assert prefilter(ctx, idx) == list(range(30))


def test_prefilter_limits_candidates_when_enough_hits():
    ctx = MatchContext(query="价格", angles=[])
    texts = ["这个价格很便宜"] * 20 + [f"无关内容{i}" for i in range(80)]
    idx = _index(texts, duration=300.0)
    candidates = prefilter(ctx, idx)
    assert 0 < len(candidates) < len(idx.segments)
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python3 -m pytest tests/test_smart_search.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'core.search_types'`）

- [ ] **Step 3: 实现类型与纯函数**

`core/search_types.py` 只放 dataclass，按 Interfaces 中的字段顺序定义；`TrendAngle` 必须在 `MatchContext` 之前定义，避免前向引用。

`core/smart_search.py` 顶部定义 Global Constraints 中的阈值常量，并实现：

- `tokenize(text)`：小写后，拉丁文用 `re.findall(r"[a-z0-9]+", text)`；CJK 用 `re.findall(r"[一-鿿]+", text)`，每个连续段长度 1 时取单字，否则取所有 2-gram。返回 list（允许重复）。
- `_context_tokens(context)`：query tokens ∪ 每个 angle 的 title + keywords tokens，返回 set。
- `build_index`：直接返回 `SearchIndex(source_file=..., filekey8=..., duration=..., segments=...)`。
- `keyword_match`：对每个 segment，`seg_tokens = set(tokenize(text))`，`hit = seg_tokens & context_tokens`，`score = len(hit) / max(1, len(context_tokens))`；`score >= KEYWORD_HIT_SCORE` 才生成 `Hit`，`reason=f"关键词命中: {', '.join(sorted(hit))}"`；`angles` 为该句命中的 angle title。
- `prefilter`：先按 `keyword_match` 同样的覆盖率计算候选；**安全网**：若 `context_tokens` 为空、或候选数为 0、或候选数 `< max(PREFILTER_MIN_CANDIDATES, int(len(segments) * PREFILTER_MIN_RATIO))`，返回 `list(range(len(segments)))`；否则返回候选索引升序列表。

- [ ] **Step 4: 运行测试，确认通过**

Run: `python3 -m pytest tests/test_smart_search.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add core/search_types.py core/smart_search.py tests/test_smart_search.py
git commit -m "feat(smart-search): 添加共享类型与关键词匹配/预筛" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: 命中合并 `merge_hits`

**Files:**
- Modify: `core/smart_search.py`
- Test: `tests/test_smart_search.py`

**Interfaces:**
- Consumes: `Hit`、`Clip`、`SearchIndex`
- Produces: `merge_hits(hits, segments, *, min_gap=2.0, pad_before=0.5, pad_after=0.5, min_dur=3.0, max_dur=120.0, top_k=10, source_file="", filekey8="", duration=None) -> list[Clip]`

- [ ] **Step 1: 写失败测试**

```python
def test_merge_hits_merges_nearby_and_splits_on_gap():
    segments = [
        {"start": 10.0, "end": 12.0, "text": "价格一"},
        {"start": 13.0, "end": 15.0, "text": "价格二"},
        {"start": 40.0, "end": 42.0, "text": "价格三"},
    ]
    hits = [Hit(0, 0.9), Hit(1, 0.8), Hit(2, 0.7)]
    clips = merge_hits(hits, segments, duration=60.0, top_k=10)
    assert len(clips) == 2
    assert clips[0].start == 9.5 and clips[0].end == 15.5
    assert clips[0].score == pytest.approx(0.85)
    assert clips[0].matched_sentences == ["价格一", "价格二"]
    assert clips[1].start == 39.5 and clips[1].end == 42.5


def test_merge_hits_clamps_padding_and_drops_short():
    segments = [{"start": 0.5, "end": 1.5, "text": "短句"}]
    clips = merge_hits([Hit(0, 0.9)], segments, duration=10.0, min_dur=3.0)
    assert clips == []


def test_merge_hits_splits_long_clip():
    segments = [
        {"start": float(i), "end": float(i + 1), "text": f"句{i}"}
        for i in range(0, 60)
    ]
    hits = [Hit(i, 0.8) for i in range(60)]
    clips = merge_hits(hits, segments, duration=60.0, max_dur=30.0, top_k=100)
    assert len(clips) > 1
    assert all(c.end - c.start <= 30.0 for c in clips)


def test_merge_hits_top_k_and_duplicate_index():
    segments = [
        {"start": 0.0, "end": 10.0, "text": "高"},
        {"start": 20.0, "end": 30.0, "text": "低"},
    ]
    hits = [Hit(0, 0.9), Hit(0, 0.5), Hit(1, 0.4)]
    clips = merge_hits(hits, segments, duration=60.0, top_k=1)
    assert len(clips) == 1
    assert clips[0].score == pytest.approx(0.9)
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python3 -m pytest tests/test_smart_search.py -k merge_hits -v`
Expected: FAIL（`NameError: merge_hits is not defined`）

- [ ] **Step 3: 实现 `merge_hits`**

算法：

1. 丢弃 `index` 越界的 Hit；同一 index 的重复 Hit 只保留最高 score。
2. 按 segment `start` 升序排列。
3. 相邻命中若 `next.start - current.end <= min_gap` 则归入同一组。
4. 每组 `start=max(0, first.start-pad_before)`，`end=min(duration, last.end+pad_after)`（`duration is None` 时用 `last.end+pad_after`）。
5. 若 `end-start > max_dur`，按 segment 边界贪心切块：每块加入下一句前检查 `next.end - block_start > max_dur - pad_before - pad_after`，超了就另起一块；每块再应用前后 padding 并裁剪到 `duration`，确保最终每块时长不超过 `max_dur`。
6. 丢弃 `end-start < min_dur` 的片段。
7. 重叠去重：两片段交集 / 较短片段时长 `>= 0.5` 时保留 score 更高者。
8. 按 score 降序取 `top_k`；同一组 `score` 为组内 Hit 平均值；`matched_sentences` 为组内句子文本；`reason` 为去重后的 reason 拼接（截断 200 字）；`angles` 为并集。

- [ ] **Step 4: 运行测试，确认通过**

Run: `python3 -m pytest tests/test_smart_search.py -k merge_hits -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add core/smart_search.py tests/test_smart_search.py
git commit -m "feat(smart-search): 实现命中合并与片段切分" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: 转写缓存

**Files:**
- Modify: `core/smart_search.py`
- Test: `tests/test_smart_search.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `CACHE_ROOT: str`
  - `transcript_cache_key(video_path: str, model_name: str = "turbo") -> str`
  - `transcript_cache_path(key: str) -> str`
  - `load_cached_transcript(key: str) -> dict | None`
  - `save_cached_transcript(key: str, data: dict) -> None`

- [ ] **Step 1: 写失败测试**

```python
def test_transcript_cache_key_changes_with_content_and_model(tmp_path):
    video = tmp_path / "a.mp4"
    video.write_bytes(b"x" * 100)
    k1 = transcript_cache_key(str(video), "turbo")
    video.write_bytes(b"x" * 101)
    k2 = transcript_cache_key(str(video), "turbo")
    k3 = transcript_cache_key(str(video), "small")
    assert k1 != k2
    assert k2 != k3
    assert len(k1) == 16


def test_transcript_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(smart_search, "CACHE_ROOT", str(tmp_path / "cache"))
    data = {"duration": 12.0, "language": "en", "segments": [{"start": 0.0, "end": 1.0, "text": "hi"}]}
    save_cached_transcript("abc123", data)
    assert load_cached_transcript("abc123") == data


def test_transcript_cache_corrupt_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(smart_search, "CACHE_ROOT", str(tmp_path / "cache"))
    path = transcript_cache_path("badbad")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not json")
    assert load_cached_transcript("badbad") is None
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python3 -m pytest tests/test_smart_search.py -k transcript_cache -v`
Expected: FAIL（`NameError`）

- [ ] **Step 3: 实现缓存函数**

- `CACHE_ROOT = os.path.join(os.path.expanduser("~"), ".ai_video_dubbing_pro", "smart_search")`
- `transcript_cache_key`：读取文件 `size`、`mtime`、首 1MB、尾 1MB；拼接 `model_name` 后 `hashlib.sha256(...).hexdigest()[:16]`；读取失败返回 `""`。
- `transcript_cache_path`：`CACHE_ROOT/transcripts/{key}.json`。
- `load_cached_transcript`：文件不存在或 JSON 解析失败返回 `None`。
- `save_cached_transcript`：`os.makedirs(..., exist_ok=True)`，UTF-8 + `ensure_ascii=False` 写入。

- [ ] **Step 4: 运行测试，确认通过**

Run: `python3 -m pytest tests/test_smart_search.py -k transcript_cache -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add core/smart_search.py tests/test_smart_search.py
git commit -m "feat(smart-search): 添加转写结果落盘缓存" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: 时长探测 / 提取音频 / Whisper 转写

**Files:**
- Modify: `core/smart_search.py`
- Test: `tests/test_smart_search.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `probe_duration(video_path: str) -> float`
  - `extract_audio(video_path: str, out_wav: str, log_cb: Callable[[str], None] | None = None) -> None`
  - `transcribe_audio(audio_path: str, model: Any = None, model_name: str = "turbo", log_cb=None) -> dict`，返回 `{"segments": [...], "language": "..."}`

- [ ] **Step 1: 写失败测试**

```python
def test_probe_duration_parses_ffprobe(monkeypatch):
    class _Result:
        returncode = 0
        stdout = "12.34\n"
        stderr = ""
    monkeypatch.setattr(smart_search.subprocess, "run", lambda *a, **k: _Result())
    assert probe_duration("demo.mp4") == pytest.approx(12.34)


def test_probe_duration_returns_zero_on_failure(monkeypatch):
    def _boom(*a, **k):
        raise FileNotFoundError("ffprobe")
    monkeypatch.setattr(smart_search.subprocess, "run", _boom)
    assert probe_duration("demo.mp4") == 0.0


def test_extract_audio_builds_ffmpeg_command(monkeypatch, tmp_path):
    calls = []

    def _run(cmd, **kwargs):
        calls.append(cmd)
        (tmp_path / "out.wav").write_bytes(b"wav")

    monkeypatch.setattr(smart_search.subprocess, "run", _run)
    extract_audio("demo.mp4", str(tmp_path / "out.wav"))
    cmd = calls[0]
    assert "-vn" in cmd and "pcm_s16le" in cmd
    assert cmd[cmd.index("-ar") + 1] == "48000"
    assert cmd[cmd.index("-ac") + 1] == "1"
    assert "-y" in cmd


def test_transcribe_audio_returns_uncompressed_segments(monkeypatch):
    captured = {}

    class _FakeModel:
        device = "cpu"
        def transcribe(self, path, **kwargs):
            captured["path"] = path
            captured["kwargs"] = kwargs
            return {"segments": [{"start": 0.0, "end": 1.0, "text": "hi"}], "language": "en"}

    class _FakeWhisper:
        @staticmethod
        def load_model(name):
            captured["model_name"] = name
            return _FakeModel()

    monkeypatch.setitem(sys.modules, "whisper", _FakeWhisper)
    result = transcribe_audio("a.wav", model_name="turbo")
    assert result["segments"] == [{"start": 0.0, "end": 1.0, "text": "hi"}]
    assert result["language"] == "en"
    assert captured["model_name"] == "turbo"
    assert captured["path"] == "a.wav"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python3 -m pytest tests/test_smart_search.py -k "probe or extract_audio or transcribe" -v`
Expected: FAIL（`NameError`）

- [ ] **Step 3: 实现三个函数**

- `probe_duration`：`subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=nw=1:nk=1", video_path], stdout=PIPE, stderr=PIPE, text=True, timeout=30)`；`float(stdout.strip())`；任何异常返回 `0.0`。
- `extract_audio`：命令 `["ffmpeg","-y","-i",video_path,"-vn","-acodec","pcm_s16le","-ar","48000","-ac","1",out_wav]`；`check=True`；失败抛 `RuntimeError(stderr)`；成功后确认 `out_wav` 存在且大小 > 0。无音轨视频由 ffmpeg 报错，调用方捕获后跳过该文件。
- `transcribe_audio`：若 `model is None`，函数内 `import whisper` 并 `whisper.load_model(model_name)`；`fp16 = getattr(model, "device", None) == "mps"`；`result = model.transcribe(audio_path, fp16=fp16)`；返回 `{"segments": result.get("segments", []), "language": result.get("language", "")}`。
- 在 `transcribe_audio` 上方写注释：**返回未压缩 segments，禁止调用 `_compress_silence()` 或复用 `subtitles_timeline`。**

- [ ] **Step 4: 运行测试，确认通过**

Run: `python3 -m pytest tests/test_smart_search.py -k "probe or extract_audio or transcribe" -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add core/smart_search.py tests/test_smart_search.py
git commit -m "feat(smart-search): 添加时长探测/音频提取/Whisper 转写" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: LLM 批量打分与熔断

**Files:**
- Modify: `core/smart_search.py`
- Test: `tests/test_smart_search.py`

**Interfaces:**
- Consumes: `MatchContext`、`Hit`、阈值常量
- Produces:
  - `class LLMUnavailableError(RuntimeError)`
  - `build_match_prompt(context: MatchContext, sentences: list[str]) -> str`
  - `parse_match_response(raw: str, expected_count: int) -> list[dict]`
  - `llm_match_sentence(context, sentence, segment_index, client, model, log_cb=None) -> Hit | None`
  - `llm_match_sentences(context, sentences, segment_indexes, client, model, batch_size=DEFAULT_BATCH_SIZE, log_cb=None) -> list[Hit]`

- [ ] **Step 1: 写失败测试**

```python
class _FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
    def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=item))]
        )


class _FakeClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=_FakeCompletions(responses))


def test_llm_match_parses_batch_json():
    client = _FakeClient(['[{"i":0,"relevant":true,"confidence":0.9,"reason":"提到价格","angle":"成本"}]'])
    hits = llm_match_sentences(
        MatchContext(query="价格", angles=[]), ["这个价格很便宜"], [0], client, "model",
    )
    assert len(hits) == 1
    assert hits[0].index == 0 and hits[0].score == pytest.approx(0.9)
    assert hits[0].angles == ["成本"]


def test_llm_match_strips_code_fence():
    raw = '```json\n[{"i":0,"relevant":true,"confidence":0.8,"reason":"ok"}]\n```'
    client = _FakeClient([raw])
    hits = llm_match_sentences(MatchContext(query="q", angles=[]), ["s"], [3], client, "m")
    assert hits[0].index == 3


def test_llm_match_filters_below_confidence_threshold():
    client = _FakeClient(['[{"i":0,"relevant":true,"confidence":0.4,"reason":"弱"}]'])
    hits = llm_match_sentences(MatchContext(query="q", angles=[]), ["s"], [0], client, "m")
    assert hits == []


def test_llm_match_retries_single_sentence_on_batch_failure():
    client = _FakeClient([
        RuntimeError("batch down"),
        '{"relevant":true,"confidence":0.7,"reason":"单句重试"}',
    ])
    hits = llm_match_sentences(MatchContext(query="q", angles=[]), ["s"], [2], client, "m")
    assert len(hits) == 1 and hits[0].index == 2


def test_llm_match_circuit_breaker():
    # 第 1 批失败计 1 次并做单句重试；第 2 批失败时计数达到 2，立即熔断
    client = _FakeClient([RuntimeError("down")] * 3)
    with pytest.raises(LLMUnavailableError):
        llm_match_sentences(
            MatchContext(query="q", angles=[]),
            ["a", "b", "c"], [0, 1, 2], client, "m", batch_size=1,
        )


def test_llm_match_passes_timeout():
    client = _FakeClient(['[{"i":0,"relevant":true,"confidence":0.9,"reason":"ok"}]'])
    llm_match_sentences(MatchContext(query="q", angles=[]), ["s"], [0], client, "m")
    assert client.chat.completions.calls[0]["timeout"] == 30
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python3 -m pytest tests/test_smart_search.py -k llm_match -v`
Expected: FAIL（`NameError`）

- [ ] **Step 3: 实现 LLM 打分**

- `build_match_prompt`：说明“你是视频内容分析助手；根据用户需求与热点角度，判断每句是否相关；跨语言语义匹配；只返回 JSON 数组”。句子编号从 0 开始。
- `parse_match_response`：去掉首尾空白与 ```json 围栏，`json.loads`；接受 list，或 `{"results": [...]}`；返回 list；解析失败抛 `ValueError`。
- `llm_match_sentence`：单句 prompt，返回 `Hit` 或 `None`（confidence < 0.5）。
- `llm_match_sentences`：按 `batch_size` 切块；每次调用 `client.chat.completions.create(model=model, messages=[...], temperature=0.3, timeout=LLM_TIMEOUT_SECONDS)`；成功则重置连续失败计数并解析。
- 批次失败：先递增连续失败计数；若已达到 `LLM_MAX_CONSECUTIVE_FAILURES`，立即抛 `LLMUnavailableError`（不再重试）；否则对该批每句做一次 `llm_match_sentence` 重试。任一批成功则计数归零。
- 只把 `relevant is True` 且 `confidence >= LLM_CONFIDENCE_HIT` 的条目转成 `Hit`；`angle` 字段非空时放入 `Hit.angles`。

- [ ] **Step 4: 运行测试，确认通过**

Run: `python3 -m pytest tests/test_smart_search.py -k llm_match -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add core/smart_search.py tests/test_smart_search.py
git commit -m "feat(smart-search): 添加 LLM 批量打分与熔断降级" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 6: 片段导出 / 报告 / 跨次去重台账

**Files:**
- Modify: `core/smart_search.py`
- Test: `tests/test_smart_search.py`

**Interfaces:**
- Consumes: `Clip`、`CACHE_ROOT`
- Produces:
  - `detect_videotoolbox() -> bool`
  - `build_clip_filename(source_path, filekey8, idx, start, end) -> str`
  - `build_export_cmd(source, out_path, start, end, codec, bitrate_mbps, vt_available=None) -> list[str]`
  - `export_clip(clip, source_path, out_dir, codec, bitrate_mbps, timeout=300) -> str`
  - `export_report(results, out_dir, meta=None) -> str`
  - `export_ledger_key(clip) -> str`
  - `load_export_ledger() -> dict`
  - `save_export_ledger(ledger) -> None`
  - `is_already_exported(clip, ledger) -> bool`
  - `mark_exported(clip, path, ledger) -> None`

- [ ] **Step 1: 写失败测试**

```python
def _clip(start=10.0, end=20.0, filekey8="abcd1234", score=0.8):
    return Clip(
        source_file="/videos/a/demo.mp4", filekey8=filekey8,
        start=start, end=end, matched_sentences=["价格"],
        score=score, reason="提到价格", angles=["成本"],
    )


def test_build_clip_filename_includes_filekey():
    name = build_clip_filename("/videos/a/demo.mp4", "abcd1234", 3, 10.0, 20.5)
    assert name == "demo_abcd1234_clip03_10.0-20.5.mp4"


def test_build_export_cmd_h264_software():
    cmd = build_export_cmd("in.mp4", "out.mp4", 10.0, 20.0, "H.264 (MP4)", 4, vt_available=False)
    assert cmd[:3] == ["ffmpeg", "-y", "-ss"]
    assert cmd[cmd.index("-c:v") + 1] == "libx264"
    assert cmd[cmd.index("-b:v") + 1] == "4M"
    assert "-map" in cmd and "0:a:0?" in cmd
    assert "-tag:v" not in cmd


def test_build_export_cmd_h265_videotoolbox():
    cmd = build_export_cmd("in.mp4", "out.mp4", 0.0, 5.0, "H.265 (HEVC)", 4, vt_available=True)
    assert cmd[cmd.index("-c:v") + 1] == "hevc_videotoolbox"
    assert cmd[cmd.index("-tag:v") + 1] == "hvc1"
    assert "+faststart" in cmd


def test_export_clip_rejects_missing_output(monkeypatch, tmp_path):
    monkeypatch.setattr(smart_search.subprocess, "run", lambda *a, **k: None)
    with pytest.raises(RuntimeError):
        export_clip(_clip(), "in.mp4", str(tmp_path), "H.264 (MP4)", 4)


def test_export_report_writes_json(tmp_path):
    path = export_report([_clip()], str(tmp_path), meta={"query": "价格"})
    data = json.loads(open(path, encoding="utf-8").read())
    assert data["meta"]["query"] == "价格"
    assert data["results"][0]["start"] == 10.0


def test_export_ledger_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(smart_search, "CACHE_ROOT", str(tmp_path / "cache"))
    clip = _clip()
    out = tmp_path / "clip.mp4"
    out.write_bytes(b"x")
    clip.clip_path = str(out)
    ledger = load_export_ledger()
    assert not is_already_exported(clip, ledger)
    mark_exported(clip, str(out), ledger)
    save_export_ledger(ledger)
    ledger2 = load_export_ledger()
    assert is_already_exported(clip, ledger2)
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python3 -m pytest tests/test_smart_search.py -k "export or ledger or clip_filename" -v`
Expected: FAIL（`NameError`）

- [ ] **Step 3: 实现导出与台账**

- `detect_videotoolbox`：模块级 `_VT_AVAILABLE: bool | None = None`；`ffmpeg -encoders` 输出含 `videotoolbox` 则 True；异常 False。
- `build_clip_filename`：`os.path.splitext(os.path.basename(source_path))[0]` + `_{filekey8}_clip{idx:02d}_{start:.1f}-{end:.1f}.mp4`。
- `build_export_cmd`：`["ffmpeg","-y","-ss",f"{start:.3f}","-t",f"{end-start:.3f}","-i",source,"-c:v",vcodec,"-b:v",f"{bitrate_mbps}M","-pix_fmt","yuv420p","-c:a","aac","-b:a","256k","-map","0:v:0","-map","0:a:0?"]`；H.265 追加 `["-tag:v","hvc1","-movflags","+faststart"]`；最后追加 `out_path`。
- `export_clip`：创建输出目录；生成文件名；`result = subprocess.run(cmd, stdout=PIPE, stderr=PIPE, timeout=timeout)`；用 `getattr(result, "returncode", 0)` 判断（便于 mock），文件不存在或大小为 0 时抛 `RuntimeError`；返回路径。
- `export_report`：`dataclasses.asdict` 序列化 Clip，写入 `out_dir/search_results.json`，`ensure_ascii=False, indent=2`；返回路径。
- 台账：`export_ledger_key = f"{clip.filekey8}:{clip.start:.1f}-{clip.end:.1f}"`；路径 `CACHE_ROOT/exported.json`；`is_already_exported` 要求 key 存在且记录的 `path` 文件仍存在；`mark_exported` 写入 `{"path": path, "score": clip.score}`。

- [ ] **Step 4: 运行测试，确认通过**

Run: `python3 -m pytest tests/test_smart_search.py -k "export or ledger or clip_filename" -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add core/smart_search.py tests/test_smart_search.py
git commit -m "feat(smart-search): 添加片段导出/报告/跨次去重" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 7: HN / V2EX 抓取、解析、缓存

**Files:**
- Create: `core/trend_sources.py`
- Create: `tests/test_trend_sources.py`

**Interfaces:**
- Consumes: `core.search_types.Hotspot`
- Produces:
  - `TREND_CACHE_DIR: str`、`TREND_CONFIG_FILE: str`
  - `fetch_hn(limit=20, timeout=8.0, session=None) -> list[Hotspot]`
  - `fetch_v2ex(limit=20, timeout=8.0, token=None, session=None) -> list[Hotspot]`
  - `fetch_hotspots(sources=("hn","v2ex"), limit=20, timeout=8.0, force_refresh=False) -> list[Hotspot]`
  - `load_trend_cache(source: str, ttl_seconds: int = 1800) -> list[Hotspot] | None`
  - `save_trend_cache(source: str, items: list[Hotspot]) -> None`

- [ ] **Step 1: 写失败测试**

```python
from core.search_types import Hotspot, TrendAngle
from core.trend_sources import (
    fetch_hn, fetch_v2ex, fetch_hotspots,
    load_trend_cache, save_trend_cache,
)
import core.trend_sources as trend_sources


class _Resp:
    def __init__(self, payload=None, text="", status=200):
        self._payload = payload
        self.text = text
        self.status_code = status
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")
    def json(self):
        return self._payload


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
    def get(self, url, **kwargs):
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


HN_PAYLOAD = {"hits": [
    {"title": "Show HN: Price tracker", "url": "https://example.com/a",
     "points": 120, "num_comments": 30, "objectID": "1"},
]}

V2EX_PAYLOAD = [
    {"title": "最近在折腾价格监控", "url": "https://v2ex.com/t/1", "replies": 12},
]

V2EX_RSS = """<?xml version="1.0"?><rss><channel><item>
<title>V2EX 热门话题</title><link>https://v2ex.com/t/2</link>
</item></channel></rss>"""


def test_fetch_hn_parses_algolia(monkeypatch):
    items = fetch_hn(limit=10, session=_Session([_Resp(HN_PAYLOAD)]))
    assert items[0].source == "hn"
    assert items[0].title == "Show HN: Price tracker"
    assert items[0].score == 120


def test_fetch_v2ex_parses_json():
    items = fetch_v2ex(limit=10, session=_Session([_Resp(V2EX_PAYLOAD)]))
    assert items[0].source == "v2ex"
    assert items[0].title == "最近在折腾价格监控"
    assert items[0].score == 12


def test_fetch_v2ex_falls_back_to_rss():
    session = _Session([RuntimeError("api down"), _Resp(text=V2EX_RSS)])
    items = fetch_v2ex(limit=10, session=session)
    assert items[0].title == "V2EX 热门话题"


def test_fetch_hotspots_survives_source_failure(monkeypatch):
    monkeypatch.setattr(trend_sources, "fetch_hn", lambda **kw: (_ for _ in ()).throw(RuntimeError("down")))
    monkeypatch.setattr(trend_sources, "fetch_v2ex", lambda **kw: [Hotspot("v2ex", "t", "u")])
    items = fetch_hotspots(force_refresh=True)
    assert len(items) == 1 and items[0].source == "v2ex"


def test_trend_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(trend_sources, "TREND_CACHE_DIR", str(tmp_path))
    save_trend_cache("hn", [Hotspot("hn", "t", "u", score=1)])
    items = load_trend_cache("hn", ttl_seconds=1800)
    assert items[0].title == "t"


def test_trend_cache_expires(tmp_path, monkeypatch):
    monkeypatch.setattr(trend_sources, "TREND_CACHE_DIR", str(tmp_path))
    save_trend_cache("hn", [Hotspot("hn", "t", "u")])
    monkeypatch.setattr(trend_sources.time, "time", lambda: 10**12)
    assert load_trend_cache("hn", ttl_seconds=60) is None
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python3 -m pytest tests/test_trend_sources.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现抓取与缓存**

- `TREND_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".ai_video_dubbing_pro", "smart_search")`
- `TREND_CONFIG_FILE = os.path.join(TREND_CACHE_DIR, "trend_config.json")`
- `_get(session, url, timeout)`：取 `session or requests`，`get(url, timeout=timeout)`，`raise_for_status()`；不自动重试（调用方各自兜底）。
- `fetch_hn`：`https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage={limit}`；解析 `hits`，URL 为空时用 `https://news.ycombinator.com/item?id={objectID}`；`score=points`、`comments=num_comments`。
- `fetch_v2ex`：若有 token，请求 `https://www.v2ex.com/api/v2/topics/hot`，头 `Authorization: Bearer {token}`；否则请求 `https://www.v2ex.com/api/topics/hot.json`。JSON 解析失败或请求异常时，请求 `https://www.v2ex.com/index.xml` 并用 `xml.etree.ElementTree.fromstring` 解析 `<item><title>/<link>`；`score=replies`（RSS 为 0）。
- `fetch_hotspots`：对每个 source，先 `load_trend_cache`（除非 `force_refresh`）；未命中则调用对应 fetch，成功后 `save_trend_cache`；单 source 异常时记录到 `errors` 并继续，返回其余结果。
- `save_trend_cache`：`{"fetched_at": time.time(), "items": [asdict(x) for x in items]}`。
- `load_trend_cache`：文件不存在/损坏返回 None；`time.time() - fetched_at > ttl_seconds` 返回 None；否则重建 `Hotspot` 列表。

- [ ] **Step 4: 运行测试，确认通过**

Run: `python3 -m pytest tests/test_trend_sources.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add core/trend_sources.py tests/test_trend_sources.py
git commit -m "feat(smart-search): 添加 HN/V2EX 热点抓取与缓存" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 8: 关键词提取与自动归纳

**Files:**
- Modify: `core/trend_sources.py`
- Test: `tests/test_trend_sources.py`

**Interfaces:**
- Consumes: `Hotspot`、`TrendAngle`
- Produces:
  - `extract_keywords(text: str, max_keywords: int = 6) -> list[str]`
  - `fallback_angles(items: list[Hotspot], max_angles: int = 8) -> list[TrendAngle]`
  - `summarize_hotspots(items, client, model, max_angles=8) -> list[TrendAngle]`

- [ ] **Step 1: 写失败测试**

```python
from types import SimpleNamespace
from core.trend_sources import extract_keywords, fallback_angles, summarize_hotspots


class _FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
    def create(self, **kwargs):
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=item))]
        )


class _FakeClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=_FakeCompletions(responses))


def test_extract_keywords_cjk_and_latin():
    kws = extract_keywords("价格 price monitor 价格 监控")
    assert "价格" in kws and "price" in kws
    assert len(kws) <= 6


def test_fallback_angles_one_per_item():
    items = [Hotspot("hn", "价格监控工具", "u"), Hotspot("v2ex", "AI 剪辑", "u2")]
    angles = fallback_angles(items, max_angles=8)
    assert len(angles) == 2
    assert angles[0].title == "价格监控工具"
    assert angles[0].why == "原始热点"


def test_summarize_hotspots_parses_json():
    client = _FakeClient(['{"angles":[{"title":"成本焦虑","keywords":["价格","省钱"],"why":"高热","source_ids":["hn:1"]}]}'])
    angles = summarize_hotspots([Hotspot("hn", "价格", "u")], client, "m")
    assert angles[0].title == "成本焦虑"
    assert angles[0].keywords == ["价格", "省钱"]


def test_summarize_hotspots_accepts_code_fence():
    client = _FakeClient(['```json\n{"angles":[{"title":"角度","keywords":[],"why":"x"}]}\n```'])
    angles = summarize_hotspots([Hotspot("hn", "价格", "u")], client, "m")
    assert angles[0].title == "角度"


def test_summarize_hotspots_falls_back_on_invalid_json():
    client = _FakeClient(["not json"])
    angles = summarize_hotspots([Hotspot("hn", "价格监控", "u")], client, "m")
    assert angles[0].title == "价格监控"


def test_summarize_hotspots_falls_back_on_llm_error():
    client = _FakeClient([RuntimeError("down")])
    angles = summarize_hotspots([Hotspot("hn", "价格监控", "u")], client, "m")
    assert angles[0].title == "价格监控"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python3 -m pytest tests/test_trend_sources.py -k "keywords or angles or summarize" -v`
Expected: FAIL（`NameError`）

- [ ] **Step 3: 实现关键词与归纳**

- `extract_keywords`：与 `smart_search.tokenize` 相同的分词规则，但本文件内独立实现（避免循环导入）；去掉英文停用词（`the/a/an/is/are/to/of/and/or/for/in/on/with`）与中文常见虚词（`的/了/是/在/和/与/就/都/也/很/我/你/他`）；按出现次数降序、保持首次出现顺序；取前 `max_keywords`。
- `fallback_angles`：每个 item 生成一个 `TrendAngle(title=item.title, keywords=extract_keywords(item.title), why="原始热点", source_ids=[f"{item.source}:{item.url}"])`，截断 `max_angles`。
- `summarize_hotspots`：prompt 只放 `title`、`source`、`score`，要求返回 `{"angles":[{"title","keywords","why","source_ids"}]}`；调用 `client.chat.completions.create(model=model, messages=[...], temperature=0.3, timeout=30)`；去除代码围栏后解析；任何异常或结构非法 → `fallback_angles`。

- [ ] **Step 4: 运行测试，确认通过**

Run: `python3 -m pytest tests/test_trend_sources.py -k "keywords or angles or summarize" -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add core/trend_sources.py tests/test_trend_sources.py
git commit -m "feat(smart-search): 添加热点关键词提取与自动归纳" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 9: 异步抓取/归纳线程 `TrendFetchThread`

**Files:**
- Create: `core/trend_thread.py`
- Test: `tests/test_trend_sources.py`

**Interfaces:**
- Consumes: `fetch_hotspots`、`summarize_hotspots`、`fallback_angles`、`load_llm_config` / `get_translation_config`
- Produces: `TrendFetchThread(QThread)`，信号 `done = pyqtSignal(list)`（热点）、`angles_ready = pyqtSignal(list)`（角度）、`failed = pyqtSignal(str)`；构造 `(sources=("hn","v2ex"), limit=20, force_refresh=False, summarize=False, max_angles=8, parent=None)`

- [ ] **Step 1: 写失败测试**

```python
def test_trend_thread_emits_done(monkeypatch):
    from core.trend_thread import TrendFetchThread
    monkeypatch.setattr("core.trend_thread.fetch_hotspots", lambda **kw: [Hotspot("hn", "t", "u")])
    thread = TrendFetchThread()
    received = []
    thread.done.connect(received.extend)
    thread.run()
    assert received[0].title == "t"


def test_trend_thread_emits_angles(monkeypatch):
    from core.trend_thread import TrendFetchThread
    monkeypatch.setattr("core.trend_thread.fetch_hotspots", lambda **kw: [Hotspot("hn", "t", "u")])
    monkeypatch.setattr("core.trend_thread.load_llm_config", lambda: {})
    monkeypatch.setattr("core.trend_thread.get_translation_config",
                        lambda cfg: {"api_key": "", "base_url": "", "model": ""})
    monkeypatch.setattr("core.trend_thread.fallback_angles",
                        lambda items, max_angles=8: [TrendAngle("兜底", [], "无 Key")])
    thread = TrendFetchThread(summarize=True)
    angles = []
    thread.angles_ready.connect(angles.extend)
    thread.run()
    assert angles[0].title == "兜底"


def test_trend_thread_emits_failed(monkeypatch):
    from core.trend_thread import TrendFetchThread

    def _boom(**kw):
        raise RuntimeError("network down")
    monkeypatch.setattr("core.trend_thread.fetch_hotspots", _boom)
    thread = TrendFetchThread()
    errors = []
    thread.failed.connect(errors.append)
    thread.run()
    assert errors == ["network down"]
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python3 -m pytest tests/test_trend_sources.py -k trend_thread -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现线程**

```python
class TrendFetchThread(QThread):
    done = pyqtSignal(list)
    angles_ready = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, sources=("hn", "v2ex"), limit=20, force_refresh=False,
                 summarize=False, max_angles=8, parent=None):
        super().__init__(parent)
        self.sources = sources
        self.limit = limit
        self.force_refresh = force_refresh
        self.summarize = summarize
        self.max_angles = max_angles

    def run(self):
        try:
            items = fetch_hotspots(
                sources=self.sources, limit=self.limit,
                force_refresh=self.force_refresh,
            )
            self.done.emit(items)
            if self.summarize:
                self.angles_ready.emit(self._build_angles(items))
        except Exception as e:
            self.failed.emit(str(e))

    def _build_angles(self, items):
        try:
            cfg = get_translation_config(load_llm_config())
            if cfg.get("api_key"):
                client = OpenAI(api_key=cfg["api_key"], base_url=cfg.get("base_url", ""))
                return summarize_hotspots(items, client, cfg.get("model", ""), self.max_angles)
        except Exception:
            pass
        return fallback_angles(items, self.max_angles)
```

`core/trend_thread.py` 顶部 `from openai import OpenAI`，便于测试替换。若 Qt 信号在无 `QApplication` 的测试进程中不触发，在 `tests/test_trend_sources.py` 顶部创建一次 `QCoreApplication([])`。

- [ ] **Step 4: 运行测试，确认通过**

Run: `python3 -m pytest tests/test_trend_sources.py -k trend_thread -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add core/trend_thread.py tests/test_trend_sources.py
git commit -m "feat(smart-search): 添加热点异步抓取与归纳线程" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 10: 检索编排线程 `SmartSearchThread`

**Files:**
- Create: `core/search_thread.py`
- Create: `tests/test_search_thread.py`

**Interfaces:**
- Consumes: Task 1–6 的全部函数；`core.llm_config.load_llm_config` / `get_translation_config`
- Produces:
  - `SmartSearchThread(QThread)`
  - 信号：`log_msg(str)`、`progress_changed(int)`、`results_ready(list)`、`error(str)`、`finished()`
  - 构造：`(scope_files, query, angles, codec, bitrate_mbps, out_dir, *, min_dur=3.0, max_dur=120.0, merge_gap=2.0, top_k=10, pad_before=0.5, pad_after=0.5, deep_mode=False, force_export=False, batch_size=10, parent=None)`
  - `stop() -> None`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_search_thread.py
import pytest
from core.search_types import Clip, Hit, MatchContext, TrendAngle
import core.search_thread as st


def _clip(path="a.mp4", start=1.0, end=10.0):
    return Clip(source_file=path, filekey8="abcd1234", start=start, end=end,
                matched_sentences=["价格"], score=0.9, reason="ok", angles=[])


def _patch_pipeline(monkeypatch, segments=None):
    segments = segments or [
        {"start": 0.0, "end": 5.0, "text": "这个价格很便宜"},
        {"start": 20.0, "end": 25.0, "text": "别的内容"},
    ]
    monkeypatch.setattr(st, "transcript_cache_key", lambda *a, **k: "abcd1234efgh5678")
    monkeypatch.setattr(st, "load_cached_transcript", lambda key: {
        "duration": 60.0, "language": "zh", "segments": segments,
    })
    monkeypatch.setattr(st, "save_cached_transcript", lambda *a, **k: None)
    monkeypatch.setattr(st, "prefilter", lambda ctx, idx: [0])
    monkeypatch.setattr(st, "keyword_match", lambda ctx, idx: [Hit(0, 0.9)])
    monkeypatch.setattr(st, "merge_hits", lambda hits, segs, **kw: [_clip(kw.get("source_file", "a.mp4"))])
    monkeypatch.setattr(st, "load_llm_config", lambda: {})
    monkeypatch.setattr(st, "get_translation_config", lambda cfg: {"api_key": "", "base_url": "", "model": ""})
    monkeypatch.setattr(st, "load_export_ledger", lambda: {})
    monkeypatch.setattr(st, "save_export_ledger", lambda ledger: None)
    monkeypatch.setattr(st, "is_already_exported", lambda clip, ledger: False)
    monkeypatch.setattr(st, "mark_exported", lambda clip, path, ledger: ledger.update({clip.filekey8: path}))
    monkeypatch.setattr(st, "export_clip", lambda *a, **k: "/tmp/clip.mp4")
    monkeypatch.setattr(st, "export_report", lambda *a, **k: "/tmp/report.json")


def test_thread_processes_all_files(monkeypatch):
    _patch_pipeline(monkeypatch)
    thread = st.SmartSearchThread(["a.mp4", "b.mp4"], "价格", [], "H.264 (MP4)", 4, "/tmp/out")
    results = []
    thread.results_ready.connect(results.extend)
    thread.run()
    assert len(results) == 2


def test_thread_continues_after_file_failure(monkeypatch):
    _patch_pipeline(monkeypatch)
    calls = {"n": 0}
    def _key(path, model="turbo"):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("broken video")
        return "abcd1234efgh5678"
    monkeypatch.setattr(st, "transcript_cache_key", _key)
    thread = st.SmartSearchThread(["bad.mp4", "good.mp4"], "价格", [], "H.264 (MP4)", 4, "/tmp/out")
    results = []
    logs = []
    thread.results_ready.connect(results.extend)
    thread.log_msg.connect(logs.append)
    thread.run()
    assert len(results) == 1
    assert any("broken video" in x for x in logs)


def test_thread_uses_keyword_fallback_when_llm_unavailable(monkeypatch):
    _patch_pipeline(monkeypatch)
    called = {"keyword": 0}
    monkeypatch.setattr(st, "get_translation_config",
                        lambda cfg: {"api_key": "k", "base_url": "u", "model": "m"})
    monkeypatch.setattr(st, "OpenAI", lambda **kw: object())
    monkeypatch.setattr(st, "llm_match_sentences",
                        lambda *a, **k: (_ for _ in ()).throw(st.LLMUnavailableError("down")))
    def _kw(ctx, idx):
        called["keyword"] += 1
        return [Hit(0, 0.9)]
    monkeypatch.setattr(st, "keyword_match", _kw)
    thread = st.SmartSearchThread(["a.mp4"], "价格", [], "H.264 (MP4)", 4, "/tmp/out")
    thread.run()
    assert called["keyword"] == 1


def test_thread_stop_before_first_file(monkeypatch):
    _patch_pipeline(monkeypatch)
    thread = st.SmartSearchThread(["a.mp4"], "价格", [], "H.264 (MP4)", 4, "/tmp/out")
    thread.running = False
    results = []
    thread.results_ready.connect(results.extend)
    thread.run()
    assert results == []
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python3 -m pytest tests/test_search_thread.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 `SmartSearchThread`**

按以下顺序实现 `run()`：

1. `self.running = True`（构造时设置）；`results = []`；`ledger = load_export_ledger()`。
2. 解析 LLM：`cfg = get_translation_config(load_llm_config())`；若 `api_key` 非空，`from openai import OpenAI; self._client = OpenAI(api_key=..., base_url=...)`，`self._model = cfg["model"]`；否则 `self._client = None`。
3. Whisper 懒加载：`_get_whisper_model()` 内部 `import whisper` 并 `whisper.load_model("turbo")`，只加载一次。
4. 对每个 `video`：
   - `if not self.running: break`
   - 用 `try/except Exception` 包住单文件全部逻辑；异常时 `log_msg.emit(f"⚠️ {video} 处理失败: {e}")` 并 `continue`。
   - `key = transcript_cache_key(video, "turbo")`；`filekey8 = key[:8]`
   - `cached = load_cached_transcript(key)`；命中则取 `segments/duration`；未命中则 `duration = probe_duration(video)`，在 `tempfile.TemporaryDirectory()` 中 `extract_audio` → `transcribe_audio(..., model=self._get_whisper_model())` → `save_cached_transcript(key, {... "duration": duration ...})`。
   - `index = build_index(segments, video, filekey8, duration)`
   - `candidates = list(range(len(segments))) if self.deep_mode else prefilter(context, index)`
   - `sentences = [segments[i]["text"] for i in candidates]`
   - 若 `self._client` 且 `sentences`：`try: hits = llm_match_sentences(context, sentences, candidates, self._client, self._model, self.batch_size)`；`except LLMUnavailableError: log; hits = keyword_match(context, index)`。否则 `hits = keyword_match(context, index)`。
   - `clips = merge_hits(hits, segments, min_gap=..., ..., source_file=video, filekey8=filekey8, duration=duration)`
   - 对每个 clip：`if not force_export and is_already_exported(clip, ledger): clip.already_exported=True; clip.clip_path = ledger[export_ledger_key(clip)]["path"]`；否则 `clip.clip_path = export_clip(...)` 并 `mark_exported`。
   - `results.extend(clips)`；`progress_changed.emit(int((i+1)/len(scope_files)*100))`。
5. `save_export_ledger(ledger)`；`results_ready.emit(results)`；`export_report(results, out_dir, meta={...})`；`finished.emit()`。所有收尾放在 `finally`，确保异常也 emit `finished`。

`core/search_thread.py` 顶部导入 `from openai import OpenAI`、`from core.llm_config import load_llm_config, get_translation_config`，并从 `core.smart_search` 导入 `LLMUnavailableError` 与其他函数，便于测试替换；构造函数中设置 `self.running = True`，`run()` 不要重置它（否则 `stop()` 后仍会继续）；`self.running = False` 的检查放在每个文件开始处。若 Qt 信号在无 `QApplication` 的测试进程中不触发，在 `tests/test_search_thread.py` 顶部创建一次 `QCoreApplication([])`。

- [ ] **Step 4: 运行测试，确认通过**

Run: `python3 -m pytest tests/test_search_thread.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add core/search_thread.py core/smart_search.py tests/test_search_thread.py
git commit -m "feat(smart-search): 添加检索编排线程" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 11: 独立检索对话框

**Files:**
- Create: `ui/smart_search_dialog.py`

**Interfaces:**
- Consumes: `TrendFetchThread`、`SmartSearchThread`、`Hotspot`、`TrendAngle`、`search_types`
- Produces: `SmartSearchDialog(QDialog)`，可直接 `SmartSearchDialog(parent).exec_()`

- [ ] **Step 1: 创建对话框骨架与布局**

按设计文档 6.2 实现：`QDialog` 约 1100×780，暗色样式对齐 `ApiConfigDialog`。必须包含以下属性与方法：

- 范围：`self.radio_single`、`self.input_single`、`self.btn_browse_single`、`self.radio_batch`、`self.input_batch`、`self.btn_browse_batch`、`self.chk_recursive`
- 意图：`self.input_query`、`self.chk_hn`、`self.chk_v2ex`、`self.spin_limit`、`self.btn_fetch`、`self.radio_auto`、`self.radio_manual`、`self.trend_list`（QListWidget，带复选框）、`self.angle_label`
- 参数：`self.spin_min_dur`、`self.spin_max_dur`、`self.spin_merge_gap`、`self.spin_top_k`、`self.chk_deep`、`self.chk_force_export`、`self.input_out_dir`、`self.btn_browse_out`
- 执行：`self.btn_start`、`self.btn_stop`、`self.progress`
- 结果：`self.results_list`、`self.btn_open_out`、`self.btn_export_report`
- 日志：`self.log_view`（QTextEdit 只读）

方法：

```python
def _collect_scope(self) -> list[str]        # 单文件或批量文件夹；批量递归可选
def _on_fetch_trends(self) -> None           # 启动 TrendFetchThread（自动模式传 summarize=True）
def _on_trends_done(self, items: list) -> None
def _on_angles_ready(self, angles: list) -> None
def _on_trends_failed(self, msg: str) -> None
def _collect_angles(self) -> list[TrendAngle]  # 自动模式用 _auto_angles；手动模式读勾选
def start_search(self) -> None
def stop_search(self) -> None
def _on_log(self, msg: str) -> None
def _on_progress(self, value: int) -> None
def _on_results(self, clips: list) -> None
def _on_error(self, msg: str) -> None
def _on_finished(self) -> None
def _on_result_double_clicked(self, item) -> None
def closeEvent(self, event) -> None
```

- [ ] **Step 2: 接线规则**

- `__init__` 初始化 `self._auto_angles = []`、`self._clips = []`、`self._close_when_finished = False`、`self._thread = None`、`self._trend_thread = None`；输出目录为空时默认 `~/Desktop/AI_智能检索_YYYYMMDD_HHMM`。
- `_on_fetch_trends`：禁用按钮，创建 `TrendFetchThread(sources=..., limit=..., force_refresh=True, summarize=self.radio_auto.isChecked())`，连接 `done/angles_ready/failed`，`start()`。
- `_on_trends_done`：填充 `trend_list`；每项 `setFlags(... | Qt.ItemIsUserCheckable)`、`setCheckState(Qt.Unchecked)`、`setData(Qt.UserRole, hotspot)`。
- `_on_angles_ready`：保存 `self._auto_angles = angles`，在 `angle_label` 中显示前 3 个标题。
- `_collect_angles`：自动模式返回 `self._auto_angles`；手动模式返回勾选项的 `TrendAngle(title=item.title, keywords=extract_keywords(item.title), why="手动选择")`。
- `start_search`：校验 scope 非空、输出目录可写、`query` 或 angles 至少一个；构造 `SmartSearchThread(...)`；连接全部信号；禁用开始/抓取，启用停止；`start()`。
- `_on_results`：`self._clips = clips`；每行显示 `f"{basename} | {start:.1f}s-{end:.1f}s | {snippet[:60]}"`，`setData(Qt.UserRole, clip.clip_path)`；已导出的行加前缀 `[已导出] `。
- `_on_finished`：恢复按钮；若 `self._close_when_finished` 为真则 `self.accept()`。
- `closeEvent`：若线程运行中，`event.ignore()`，`stop()`，`self._close_when_finished=True`，日志提示等待当前视频；否则 `event.accept()`。
- 双击结果：`subprocess.run(["open", path])`，路径为空时忽略。

- [ ] **Step 3: 冒烟测试**

Run:

```bash
QT_QPA_PLATFORM=offscreen python3 -c "
from PyQt5.QtWidgets import QApplication
app = QApplication([])
from ui.smart_search_dialog import SmartSearchDialog
d = SmartSearchDialog()
print('ok')
d.close()
"
```

Expected: 输出 `ok`，无异常。

- [ ] **Step 4: 提交**

```bash
git add ui/smart_search_dialog.py
git commit -m "feat(smart-search): 添加独立检索对话框" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 12: 主界面接线、功能开关、打包配置

**Files:**
- Modify: `core/config.py`
- Modify: `ui/ui_main.py:10-20`（import）、`:677-688`（按钮行）、`:1014-1020`（新增方法位置）
- Modify: `AI视频配音Pro.spec`（`hidden_imports`）

**Interfaces:**
- Consumes: `SmartSearchDialog`
- Produces: `ENABLE_SMART_SEARCH: bool`；`MainWindow.btn_smart_search`、`MainWindow.open_smart_search()`

- [ ] **Step 1: 写验证测试（失败）**

```python
# tests/test_smart_search.py 追加
def test_feature_flag_defaults_on(monkeypatch):
    import importlib, core.config
    monkeypatch.delenv("AI_VIDEO_SMART_SEARCH", raising=False)
    importlib.reload(core.config)
    assert core.config.ENABLE_SMART_SEARCH is True


def test_feature_flag_can_be_disabled(monkeypatch):
    import importlib, core.config
    monkeypatch.setenv("AI_VIDEO_SMART_SEARCH", "0")
    importlib.reload(core.config)
    assert core.config.ENABLE_SMART_SEARCH is False
    monkeypatch.delenv("AI_VIDEO_SMART_SEARCH")
    importlib.reload(core.config)
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python3 -m pytest tests/test_smart_search.py -k feature_flag -v`
Expected: FAIL（`AttributeError: ENABLE_SMART_SEARCH`）

- [ ] **Step 3: 实现开关与接线**

`core/config.py` 增加：

```python
ENABLE_SMART_SEARCH = os.environ.get("AI_VIDEO_SMART_SEARCH", "1") != "0"
```

`ui/ui_main.py`：

- import 行加入 `ENABLE_SMART_SEARCH`。
- 在 `self.btn_api_config` 之后追加按钮：

```python
self.btn_smart_search = QPushButton("🔍 智能检索")
self.btn_smart_search.clicked.connect(self.open_smart_search)
self.btn_smart_search.setVisible(ENABLE_SMART_SEARCH)
config_btn_layout.addWidget(self.btn_smart_search)
```

- 在 `open_api_config` 之后新增：

```python
def open_smart_search(self):
    """打开智能检索对话框（懒加载，失败不影响主程序）"""
    if not ENABLE_SMART_SEARCH:
        return self.log("ℹ️ 智能检索功能已关闭")
    try:
        from ui.smart_search_dialog import SmartSearchDialog
        SmartSearchDialog(self).exec_()
    except Exception as e:
        self.log(f"⚠️ 智能检索不可用: {e}")
```

`AI视频配音Pro.spec` 的 `hidden_imports` 追加：

```python
"core.search_types", "core.smart_search", "core.trend_sources",
"core.trend_thread", "core.search_thread", "ui.smart_search_dialog",
```

- [ ] **Step 4: 运行验证**

Run:

```bash
python3 -m pytest tests/test_smart_search.py -k feature_flag -v
QT_QPA_PLATFORM=offscreen AI_VIDEO_SMART_SEARCH=1 python3 -c "
from PyQt5.QtWidgets import QApplication
app = QApplication([])
from ui.ui_main import MainWindow
w = MainWindow()
print('button:', w.btn_smart_search.text())
"
```

Expected: 2 passed；输出 `button: 🔍 智能检索`。若 `MainWindow` 因 InsightFace 导入过慢，给命令加 `timeout 180`，不要跳过该验证。

- [ ] **Step 5: 提交**

```bash
git add core/config.py ui/ui_main.py AI视频配音Pro.spec tests/test_smart_search.py
git commit -m "feat(smart-search): 主界面接线与功能开关" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 13: 全量回归、端到端验证与文档

**Files:**
- Modify: `HANDOFF_v4.4.0_20260903.md`
- Modify: `AI视频配音Pro-使用手册.md`（新增“智能检索”章节）
- Possibly modify: `智能视频检索v4.4.0设计方案20261102.md`（记录实施结果）

- [ ] **Step 1: 全量测试**

Run: `python3 -m pytest tests/ -q`
Expected: 基线 64 passed + 1 skipped，新增测试全部通过；无新增 skip。

- [ ] **Step 2: 关闭开关验证**

Run:

```bash
QT_QPA_PLATFORM=offscreen AI_VIDEO_SMART_SEARCH=0 python3 -c "
from PyQt5.QtWidgets import QApplication
app = QApplication([])
from ui.ui_main import MainWindow
w = MainWindow()
assert not w.btn_smart_search.isVisible()
print('hidden ok')
"
```

Expected: 输出 `hidden ok`。

- [ ] **Step 3: 端到端手工验证**

准备一个含已知关键词的短视频（例如用 ffmpeg 生成 30 秒测试片，并在第 12 秒附近说话），执行：

1. 启动 `python3 entry.py`，点击「🔍 智能检索」。
2. 选择单个视频；提示词输入视频中真实出现的词；关闭热点，直接检索。
3. 确认结果列表出现片段，双击能播放，起止时间与源视频对齐（误差 ≤ 0.5 秒）。
4. 再次检索同一视频，确认转写缓存命中、已导出片段被标记。
5. 断开网络后点击「抓取热榜」，确认 UI 不崩溃、日志显示失败并仍可用提示词检索。

- [ ] **Step 4: 更新文档**

`HANDOFF_v4.4.0_20260903.md` 增加“实施状态”段落：列出新增文件、测试数量、已知限制（Whisper 停止需等当前文件、HN 网络依赖）。`AI视频配音Pro-使用手册.md` 增加「智能检索」操作步骤和输出目录说明。

- [ ] **Step 5: 提交**

```bash
git add HANDOFF_v4.4.0_20260903.md AI视频配音Pro-使用手册.md
git commit -m "docs(v4.4.0): 更新智能检索实施状态与使用说明" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

## Self-Review

- **Spec coverage**：设计文档第 5–10 节（架构、UI、热点、检索、导出、线程、零影响）分别由 Task 1–12 覆盖；第 11–16 节（分支、测试、验收）由 Task 13 与 Global Constraints 覆盖。
- **Type consistency**：`SearchIndex/Hit/Clip/MatchContext/Hotspot/TrendAngle` 统一定义在 `core/search_types.py`；`merge_hits` 签名在 Task 2 与 Task 10 一致；`llm_match_sentences` 的 `segment_indexes` 在 Task 5/10 一致。
- **Review Focus**：5 类高风险输入均在对应任务中安排了测试（见 Review Focus 列表）。
- **Proportion**：计划以接口、测试与算法要点为主，未复制完整实现。
