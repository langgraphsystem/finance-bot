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


class TaskStatus(enum.StrEnum):
    pending = "pending"
    in_progress = "in_progress"
    done = "done"
    cancelled = "cancelled"


class TaskPriority(enum.StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


class ContactRole(enum.StrEnum):
    client = "client"
    vendor = "vendor"
    partner = "partner"
    friend = "friend"
    family = "family"
    doctor = "doctor"
    other = "other"


class MonitorType(enum.StrEnum):
    price = "price"
    news = "news"
    competitor = "competitor"
    exchange_rate = "exchange_rate"


class SubscriptionStatus(enum.StrEnum):
    active = "active"
    past_due = "past_due"
    cancelled = "cancelled"
    trial = "trial"


class ChannelType(enum.StrEnum):
    telegram = "telegram"
    whatsapp = "whatsapp"
    slack = "slack"
    sms = "sms"


class BookingStatus(enum.StrEnum):
    scheduled = "scheduled"
    confirmed = "confirmed"
    completed = "completed"
    cancelled = "cancelled"
    no_show = "no_show"


class InteractionChannel(enum.StrEnum):
    phone = "phone"
    telegram = "telegram"
    whatsapp = "whatsapp"
    sms = "sms"
    email = "email"


class InteractionDirection(enum.StrEnum):
    inbound = "inbound"
    outbound = "outbound"
