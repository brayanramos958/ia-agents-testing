"""
Abstract interface for RAG (Retrieval-Augmented Generation) operations.

Provides semantic search over resolved tickets and the ability to add
new resolutions to the knowledge base in real time.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List


@dataclass
class SolutionItem:
    """A single resolved ticket retrieved as a potential solution."""
    ticket_name: str        # e.g. "TCK-0001"
    ticket_id: int
    category: str
    ticket_type: str
    description: str
    motivo_resolucion: str  # Resolution text (Odoo field name)
    score: float            # Similarity score 0.0–1.0 (higher = more similar)


@dataclass
class SuggestionResult:
    """Result of a similarity search in the knowledge base."""
    solutions_found: bool
    solutions: List[SolutionItem] = field(default_factory=list)
    # Highest similarity score found. Used to decide if a solution
    # should be presented to the user before ticket creation.
    # Threshold is configured via settings.rag_similarity_threshold (default 0.6)
    confidence: float = 0.0


class IRAGPort(ABC):

    @abstractmethod
    def search_similar(self, query: str, category: str = None,
                       k: int = 5) -> SuggestionResult:
        """
        Search for resolved tickets similar to the given query.

        Args:
            query: Natural language description of the problem
            category: Optional category name to narrow search
            k: Maximum number of results to return

        Returns:
            SuggestionResult with solutions and confidence score
        """

    @abstractmethod
    def add_resolved_ticket(self, ticket_id: int, ticket_name: str,
                            ticket_type: str, category: str,
                            description: str, motivo_resolucion: str) -> bool:
        """
        Add a newly resolved ticket to the knowledge base.
        Called immediately after a ticket is resolved so the knowledge base
        grows in real time.

        Returns True if added successfully.
        """

    @abstractmethod
    def initialize_from_resolved_tickets(self, tickets: list) -> int:
        """
        Seed the vector store from a list of resolved tickets.
        Called once at application startup.

        Args:
            tickets: List of dicts with keys matching get_resolved_tickets() output

        Returns:
            Number of tickets loaded
        """

    @abstractmethod
    def count(self) -> int:
        """Returns the number of documents currently in the vector store."""
