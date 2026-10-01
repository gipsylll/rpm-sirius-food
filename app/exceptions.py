"""Доменные исключения. Не зависят от HTTP и СУБД."""


class DomainError(Exception):
    """Базовая ошибка предметной области."""


class NotFoundError(DomainError):
    """Запрошенная сущность отсутствует."""


class ForbiddenError(DomainError):
    """Операция запрещена состоянием сущности."""


class BusinessRuleError(DomainError):
    """Нарушено бизнес-правило."""
