using System;
using System.Collections.Generic;

namespace ServiceLayer.Models
{
    public class PricingPlanDto
    {
        public string Name { get; set; } = string.Empty;
        public int MaxQuestionsPerDay { get; set; }
        public int MaxDocuments { get; set; }
        public int MaxSubjects { get; set; }
        public int MaxMembers { get; set; }
        public int MaxFileSizeMb { get; set; }
        public bool AllowGemini { get; set; }
        public bool IsUnlimited { get; set; }
        public decimal MonthlyPrice { get; set; }
        public string Currency { get; set; } = "VND";
        public bool IsCurrent { get; set; }
    }

    public class CheckoutSessionDto
    {
        public int Id { get; set; }
        public string ReferenceCode { get; set; } = string.Empty;
        public string PlanName { get; set; } = string.Empty;
        public decimal Amount { get; set; }
        public string Currency { get; set; } = "VND";
        public string Status { get; set; } = string.Empty;
        public DateTime CreatedAt { get; set; }
    }

    public class BillingInvoiceDto
    {
        public string InvoiceNumber { get; set; } = string.Empty;
        public string PlanName { get; set; } = string.Empty;
        public decimal Amount { get; set; }
        public string Currency { get; set; } = "VND";
        public string Status { get; set; } = string.Empty;
        public DateTime CreatedAt { get; set; }
        public DateTime? PaidAt { get; set; }
    }

    public class BillingPortalDto
    {
        public OrganizationDto? Organization { get; set; }
        public SubscriptionStatusDto? Subscription { get; set; }
        public List<PricingPlanDto> Plans { get; set; } = new();
        public List<BillingInvoiceDto> Invoices { get; set; } = new();
        public bool CanManageBilling { get; set; }
    }
}
