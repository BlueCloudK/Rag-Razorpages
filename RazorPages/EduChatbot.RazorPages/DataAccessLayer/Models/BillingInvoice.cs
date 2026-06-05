using System;
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace DataAccessLayer.Models
{
    public class BillingInvoice
    {
        [Key]
        public int Id { get; set; }

        public int OrganizationId { get; set; }

        [ForeignKey("OrganizationId")]
        public Organization? Organization { get; set; }

        public int PlanId { get; set; }

        [ForeignKey("PlanId")]
        public SubscriptionPlan? Plan { get; set; }

        [Required]
        [MaxLength(40)]
        public string InvoiceNumber { get; set; } = string.Empty;

        public decimal Amount { get; set; }

        [MaxLength(8)]
        public string Currency { get; set; } = "VND";

        [Required]
        [MaxLength(30)]
        public string Status { get; set; } = "Paid";

        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
        public DateTime? PaidAt { get; set; }
    }
}
