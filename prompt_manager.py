from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping


VARIABLE_RE = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")
VALID_PROMPT_TYPES = {"pdf_form_fill", "generic"}
LEGACY_PROMPT_TYPE_ALIASES = {
    "": "generic",
    "general": "generic",
    "primary": "generic",
    "secondary": "generic",
    "tertiary": "generic",
}


def normalize_prompt_type(value: object) -> str:
    prompt_type = str(value or "").strip() or "generic"
    prompt_type = LEGACY_PROMPT_TYPE_ALIASES.get(prompt_type, prompt_type)
    return prompt_type if prompt_type in VALID_PROMPT_TYPES else "generic"


@dataclass
class Prompt:
    id: str
    name: str
    content: str
    is_default: bool = False
    prompt_type: str = "generic"


class PromptManager:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.prompts: list[Prompt] = []
        self.load()

    def load(self) -> list[Prompt]:
        if not self.path.exists():
            self.prompts = []
            return self.prompts

        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.prompts = [
            Prompt(
                id=str(item.get("id") or uuid.uuid4().hex),
                name=str(item.get("name") or "Prompt sans nom"),
                content=str(item.get("content") or ""),
                is_default=bool(item.get("is_default")),
                prompt_type=normalize_prompt_type(item.get("prompt_type")),
            )
            for item in data
            if isinstance(item, dict)
        ]
        self._ensure_single_default()
        return self.prompts

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_single_default()
        self.path.write_text(
            json.dumps([asdict(prompt) for prompt in self.prompts], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list_prompts(self, prompt_type: str | list[str] | tuple[str, ...] | set[str] | None = None) -> list[Prompt]:
        if prompt_type is None:
            return list(self.prompts)
        if isinstance(prompt_type, (list, tuple, set)):
            prompt_types = {normalize_prompt_type(item) for item in prompt_type}
            return [prompt for prompt in self.prompts if prompt.prompt_type in prompt_types]
        normalized = normalize_prompt_type(prompt_type)
        return [prompt for prompt in self.prompts if prompt.prompt_type == normalized]

    def get(self, prompt_id: str) -> Prompt | None:
        for prompt in self.prompts:
            if prompt.id == prompt_id:
                return prompt
        return None

    def get_by_name(self, name: str) -> Prompt | None:
        for prompt in self.prompts:
            if prompt.name == name:
                return prompt
        return None

    def get_default(self, prompt_type: str | list[str] | tuple[str, ...] | set[str] | None = None) -> Prompt | None:
        prompts = self.list_prompts(prompt_type)
        for prompt in prompts:
            if prompt.is_default:
                return prompt
        return prompts[0] if prompts else None

    def get_default_any(self) -> Prompt | None:
        for prompt in self.prompts:
            if prompt.is_default:
                return prompt
        return self.prompts[0] if self.prompts else None

    def create(
        self,
        name: str,
        content: str = "",
        is_default: bool = False,
        *,
        prompt_type: str = "generic",
        prompt_id: str | None = None,
    ) -> Prompt:
        prompt = Prompt(
            id=prompt_id or uuid.uuid4().hex,
            name=name.strip() or "Prompt sans nom",
            content=content,
            is_default=is_default,
            prompt_type=normalize_prompt_type(prompt_type),
        )
        self.prompts.append(prompt)
        if is_default:
            self.set_default(prompt.id)
        else:
            self.save()
        return prompt

    def update(
        self,
        prompt_id: str,
        *,
        name: str | None = None,
        content: str | None = None,
        prompt_type: str | None = None,
    ) -> Prompt:
        prompt = self.get(prompt_id)
        if prompt is None:
            raise KeyError(f"Prompt introuvable: {prompt_id}")
        if name is not None:
            prompt.name = name.strip() or prompt.name
        if content is not None:
            prompt.content = content
        if prompt_type is not None:
            prompt.prompt_type = normalize_prompt_type(prompt_type)
        self.save()
        return prompt

    def duplicate(self, prompt_id: str, new_name: str | None = None) -> Prompt:
        prompt = self.get(prompt_id)
        if prompt is None:
            raise KeyError(f"Prompt introuvable: {prompt_id}")
        return self.create(
            new_name or f"{prompt.name} - copie",
            prompt.content,
            is_default=False,
            prompt_type=prompt.prompt_type,
        )

    def delete(self, prompt_id: str) -> None:
        target = self.get(prompt_id)
        if target is None:
            return
        same_type_prompts = [prompt for prompt in self.prompts if prompt.prompt_type == target.prompt_type]
        if len(same_type_prompts) <= 1:
            raise ValueError("Il faut conserver au moins un prompt de ce type.")
        was_default = bool(target.is_default)
        self.prompts = [prompt for prompt in self.prompts if prompt.id != prompt_id]
        if was_default and self.prompts:
            for prompt in self.prompts:
                if prompt.prompt_type == target.prompt_type:
                    prompt.is_default = True
                    break
        self.save()

    def set_default(self, prompt_id: str) -> None:
        found = False
        target = self.get(prompt_id)
        if target is None:
            raise KeyError(f"Prompt introuvable: {prompt_id}")
        for prompt in self.prompts:
            if prompt.prompt_type != target.prompt_type:
                continue
            prompt.is_default = prompt.id == prompt_id
            found = found or prompt.is_default
        if not found:
            raise KeyError(f"Prompt introuvable: {prompt_id}")
        self.save()

    def render_prompt(self, prompt: Prompt | str, variables: Mapping[str, object]) -> str:
        template = prompt.content if isinstance(prompt, Prompt) else str(prompt)
        normalized = {str(key): "" if value is None else str(value) for key, value in variables.items()}

        def replace(match: re.Match[str]) -> str:
            return normalized.get(match.group(1), "")

        return VARIABLE_RE.sub(replace, template).strip()

    def _ensure_single_default(self) -> None:
        defaults_seen: set[str] = set()
        types_seen: list[str] = []
        for prompt in self.prompts:
            prompt.prompt_type = normalize_prompt_type(prompt.prompt_type)
            if prompt.prompt_type not in types_seen:
                types_seen.append(prompt.prompt_type)
            if prompt.is_default and prompt.prompt_type not in defaults_seen:
                defaults_seen.add(prompt.prompt_type)
            else:
                prompt.is_default = False
        for prompt_type in types_seen:
            if prompt_type in defaults_seen:
                continue
            for prompt in self.prompts:
                if prompt.prompt_type == prompt_type:
                    prompt.is_default = True
                    defaults_seen.add(prompt_type)
                    break
