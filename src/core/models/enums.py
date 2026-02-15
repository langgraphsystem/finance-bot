import enum


class TransactionType(enum.StrEnum):
    income = "income"
    expense = "expense"


class Scope(enum.StrEnum):
    business = "business"
    family = "family"
    personal = "personal"


class UserRole(enum.StrEnum):
    owner = "owner"
    member = "member"


class DocumentType(enum.StrEnum):
    receipt = "receipt"
    invoice = "invoice"
    rate_confirmation = "rate_confirmation"
    fuel_receipt = "fuel_receipt"
    other = "other"


class LoadStatus(enum.StrEnum):
    pending = "pending"
    delivered = "delivered"
    paid = "paid"
    overdue = "overdue"


class MessageRole(enum.StrEnum):
    user = "user"
    assistant = "assistant"


class ConversationState(enum.StrEnum):
    onboarding = "onboarding"
    onboarding_awaiting_choice = "onboarding_awaiting_choice"
    onboarding_awaiting_activity = "onboarding_awaiting_activity"
    onboarding_awaiting_invite_code = "onboarding_awaiting_invite_code"
    normal = "normal"
    correcting = "correcting"
    awaiting_confirm = "awaiting_confirm"


class PaymentFrequency(enum.StrEnum):
    weekly = "weekly"
    monthly = "monthly"
    quarterly = "quarterly"
    yearly = "yearly"


class BudgetPeriod(enum.StrEnum):
    weekly = "weekly"
    monthly = "monthly"


class LifeEventType(enum.StrEnum):
    note = "note"
    food = "food"
    drink = "drink"
    mood = "mood"
    task = "task"
    reflection = "reflection"
