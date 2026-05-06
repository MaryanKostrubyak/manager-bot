from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO

from loguru import logger
from PIL import Image, UnidentifiedImageError

try:
    from openai import AsyncOpenAI, OpenAIError
except Exception:  # pragma: no cover - optional dependency
    AsyncOpenAI = None
    OpenAIError = Exception

from app.core.config import Settings


@dataclass
class ReceiptData:
    amount: Decimal | None
    currency: str | None
    merchant: str | None
    category_hint: str | None
    description: str
    occurred_at: datetime | None


class GPTReceiptParser:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        if settings.openai_api_key and AsyncOpenAI:
            self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        else:
            self._client = None
        self.model = settings.openai_model

    @property
    def enabled(self) -> bool:
        return self._client is not None

    async def parse(self, payload: bytes) -> ReceiptData:
        if not self.enabled:
            raise RuntimeError("AI-розпізнавання чеків недоступне. Додай OPENAI_API_KEY у налаштування.")

        try:
            encoded_image = self._prepare_image(payload)
        except UnidentifiedImageError:
            raise RuntimeError("Не вдалося прочитати фото. Спробуй зробити чіткіше зображення.") from None

        prompt = (
            "Ти аналізуєш фото фіскального чека. Поверни відповідь строго у форматі JSON:\n"
            '{"total": number | null, "currency": "UAH"|"USD"|...|null, '
            '"merchant": string | null, "category_hint": string | null, '
            '"occurred_at": "YYYY-MM-DD" | null}. '
            "Якщо даних немає, став null. Без пояснень."
        )

        try:
            response = await self._client.responses.create(
                model=self.model,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": prompt},
                            {"type": "input_image", "image": {"base64": encoded_image}},
                        ],
                    }
                ],
            )
        except OpenAIError as exc:  # pragma: no cover - network dependency
            logger.warning("GPT receipt parser error: {}", exc)
            raise RuntimeError("Не вдалося звернутися до AI-сервісу. Спробуй пізніше.") from exc

        text = self._extract_text(response)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            raise RuntimeError("AI не зміг розпізнати чек. Спробуй сфотографувати чіткіше.") from None

        amount = self._parse_amount(parsed.get("total"))
        currency = parsed.get("currency")
        merchant = self._clean_text(parsed.get("merchant"))
        category_hint = self._clean_text(parsed.get("category_hint"))
        occurred_at = self._parse_date(parsed.get("occurred_at"))
        description_parts = [part for part in (merchant, category_hint) if part]
        description = " / ".join(description_parts) if description_parts else "Чек AI"

        return ReceiptData(
            amount=amount,
            currency=currency,
            merchant=merchant,
            category_hint=category_hint,
            description=description,
            occurred_at=occurred_at,
        )

    def _prepare_image(self, payload: bytes) -> str:
        with Image.open(BytesIO(payload)) as image:
            image = image.convert("RGB")
            image.thumbnail((1024, 1024))
            buffer = BytesIO()
            image.save(buffer, format="JPEG", quality=85)
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    def _extract_text(self, response) -> str:
        try:
            return response.output[0].content[0].text
        except (AttributeError, IndexError, KeyError):
            raise RuntimeError("AI повернув порожню відповідь.") from None

    def _parse_amount(self, value) -> Decimal | None:
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return None

    def _parse_date(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return None

    def _clean_text(self, value: str | None) -> str | None:
        if not value:
            return None
        cleaned = value.strip()
        return cleaned or None
