import enum


class TransactionType(str, enum.Enum):
    income = "income"
    expense = "expense"


class Scope(str, enum.Enum):
    business = "business"
    family = "family"
    personal = "personal"


class UserRole(str, enum.Enum):
    owner = "owner"
    member = "member"


class DocumentType(str, enum.Enum):
    receipt = "receipt"
    invoice = "invoice"
    rate_confirmation = "rate_confirmation"
    fuel_receipt = "fuel_receipt"
    other = "other"


class LoadStatus(str, enum.Enum):
    pending = "pending"
    delivered = "delivered"
    paid = "paid"
    overdue = "overdue"


class MessageRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"


class ConversationState(str, enum.Enum):
    onboarding = "onboarding"
    onboarding_awaiting_choice = "onboarding_awaiting_choice"
    onboarding_awaiting_activity = "onboarding_awaiting_activity"
    onboarding_awaiting_invite_code = "onboarding_awaiting_invite_code"
    normal = "normal"
    correcting = "correcting"
    awaiting_confirm = "awaiting_confirm"


class PaymentFrequency(str, enum.Enum):
    weekly = "weekly"
    monthly = "monthly"
    quarterly = "quarterly"
    yearly = "yearly"


class BudgetPeriod(str, enum.Enum):
    weekly = "weekly"
    monthly = "monthly"
