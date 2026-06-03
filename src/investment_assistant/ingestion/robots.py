"""robots.txt checks for safe data ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse
from urllib.robotparser import RobotFileParser

from investment_assistant.ingestion.transport import HttpTransport


@dataclass(frozen=True)
class RobotsDecision:
    """Result of a robots.txt check."""

    allowed: bool
    robots_url: str
    reason: str


class RobotsChecker:
    """Fetch and evaluate robots.txt with an injectable transport."""

    def __init__(
        self,
        transport: HttpTransport,
        *,
        user_agent: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.transport = transport
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self._parsers: dict[str, RobotFileParser] = {}

    def can_fetch(self, url: str) -> RobotsDecision:
        """Return whether the configured user-agent may fetch the URL."""

        robots_url = self.robots_url_for(url)
        parser = self._parsers.get(robots_url)
        if parser is None:
            parser = self._load_parser(robots_url)
            self._parsers[robots_url] = parser
        allowed = bool(parser.can_fetch(self.user_agent, url))
        reason = "allowed_by_robots" if allowed else "blocked_by_robots"
        return RobotsDecision(allowed=allowed, robots_url=robots_url, reason=reason)

    @staticmethod
    def robots_url_for(url: str) -> str:
        """Build the robots.txt URL for a target URL."""

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            msg = f"Only absolute http(s) URLs are supported: {url}"
            raise ValueError(msg)
        return urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))

    def _load_parser(self, robots_url: str) -> RobotFileParser:
        parser = RobotFileParser(robots_url)
        response = self.transport.get(
            robots_url,
            timeout_seconds=self.timeout_seconds,
            user_agent=self.user_agent,
        )
        if response.status_code == 404:
            parser.parse([])
            return parser
        if response.status_code >= 400:
            parser.parse(["User-agent: *", "Disallow: /"])
            return parser
        text = response.body.decode("utf-8", errors="replace")
        parser.parse(text.splitlines())
        return parser
