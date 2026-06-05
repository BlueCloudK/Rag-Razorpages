using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using DataAccessLayer.Data;
using DataAccessLayer.Models;
using Microsoft.EntityFrameworkCore;
using ServiceLayer.Models;

namespace ServiceLayer.Services
{
    public class BillingService : IBillingService
    {
        private readonly ApplicationDbContext _context;
        private readonly IOrganizationService _organizationService;
        private readonly ISubscriptionService _subscriptionService;
        private readonly IAuditLogService _auditLogService;

        public BillingService(ApplicationDbContext context, IOrganizationService organizationService, ISubscriptionService subscriptionService, IAuditLogService auditLogService)
        {
            _context = context;
            _organizationService = organizationService;
            _subscriptionService = subscriptionService;
            _auditLogService = auditLogService;
        }

        public async Task<List<PricingPlanDto>> GetPricingAsync()
        {
            var current = await _subscriptionService.GetCurrentStatusAsync();
            var plans = await _context.SubscriptionPlans.OrderBy(p => p.Id).ToListAsync();
            return plans.Select(p => ToPricingDto(p, current.PlanName)).ToList();
        }

        public async Task<BillingPortalDto> GetPortalAsync()
        {
            var org = await _organizationService.GetCurrentOrganizationAsync();
            var invoices = org == null
                ? new List<BillingInvoiceDto>()
                : await _context.BillingInvoices
                    .Include(i => i.Plan)
                    .Where(i => i.OrganizationId == org.Id)
                    .OrderByDescending(i => i.CreatedAt)
                    .Select(i => new BillingInvoiceDto
                    {
                        InvoiceNumber = i.InvoiceNumber,
                        PlanName = i.Plan!.Name,
                        Amount = i.Amount,
                        Currency = i.Currency,
                        Status = i.Status,
                        CreatedAt = i.CreatedAt,
                        PaidAt = i.PaidAt
                    })
                    .ToListAsync();

            return new BillingPortalDto
            {
                Organization = org,
                Subscription = await _subscriptionService.GetCurrentStatusAsync(),
                Plans = await GetPricingAsync(),
                Invoices = invoices,
                CanManageBilling = await _organizationService.CanManageCurrentOrganizationAsync()
            };
        }

        public async Task<CheckoutSessionDto?> StartCheckoutAsync(string planName)
        {
            if (!await _organizationService.CanManageCurrentOrganizationAsync())
                return null;

            var orgId = await _organizationService.GetCurrentOrganizationIdAsync();
            if (!orgId.HasValue)
                return null;

            var plan = await _context.SubscriptionPlans.FirstOrDefaultAsync(p => p.Name == planName);
            if (plan == null)
                return null;

            var checkout = new CheckoutSession
            {
                OrganizationId = orgId.Value,
                PlanId = plan.Id,
                Status = "Pending",
                ReferenceCode = "CHK-" + DateTime.UtcNow.ToString("yyyyMMddHHmmss") + "-" + Guid.NewGuid().ToString("N")[..6].ToUpperInvariant(),
                Amount = GetMonthlyPrice(plan.Name),
                Currency = "VND",
                CreatedAt = DateTime.UtcNow
            };

            _context.CheckoutSessions.Add(checkout);
            await _context.SaveChangesAsync();
            await _auditLogService.RecordAsync("StartCheckout", "CheckoutSession", checkout.Id, null, orgId.Value, $"Started checkout for {plan.Name}.");
            return ToCheckoutDto(checkout, plan.Name);
        }

        public async Task<CheckoutSessionDto?> GetCheckoutAsync(int id)
        {
            var orgId = await _organizationService.GetCurrentOrganizationIdAsync();
            var checkout = await _context.CheckoutSessions
                .Include(c => c.Plan)
                .FirstOrDefaultAsync(c => c.Id == id && c.OrganizationId == orgId);

            return checkout == null ? null : ToCheckoutDto(checkout, checkout.Plan?.Name ?? "");
        }

        public async Task<bool> PayCheckoutAsync(int id)
        {
            if (!await _organizationService.CanManageCurrentOrganizationAsync())
                return false;

            var orgId = await _organizationService.GetCurrentOrganizationIdAsync();
            var checkout = await _context.CheckoutSessions
                .Include(c => c.Plan)
                .FirstOrDefaultAsync(c => c.Id == id && c.OrganizationId == orgId && c.Status == "Pending");

            if (checkout == null || checkout.Plan == null)
                return false;

            var active = await _context.OrganizationSubscriptions
                .Where(s => s.OrganizationId == checkout.OrganizationId && s.IsActive)
                .ToListAsync();

            foreach (var subscription in active)
            {
                subscription.IsActive = false;
                subscription.EndDate = DateTime.UtcNow;
            }

            _context.OrganizationSubscriptions.Add(new OrganizationSubscription
            {
                OrganizationId = checkout.OrganizationId,
                PlanId = checkout.PlanId,
                IsActive = true,
                StartDate = DateTime.UtcNow
            });

            checkout.Status = "Paid";
            checkout.PaidAt = DateTime.UtcNow;

            _context.BillingInvoices.Add(new BillingInvoice
            {
                OrganizationId = checkout.OrganizationId,
                PlanId = checkout.PlanId,
                InvoiceNumber = "INV-" + DateTime.UtcNow.ToString("yyyyMMdd") + "-" + checkout.Id.ToString("D5"),
                Amount = checkout.Amount,
                Currency = checkout.Currency,
                Status = "Paid",
                CreatedAt = DateTime.UtcNow,
                PaidAt = DateTime.UtcNow
            });

            await _context.SaveChangesAsync();
            await _auditLogService.RecordAsync("PayCheckout", "CheckoutSession", checkout.Id, null, checkout.OrganizationId, $"Paid checkout for {checkout.Plan.Name}.");
            return true;
        }

        public async Task<bool> CancelSubscriptionAsync()
        {
            if (!await _organizationService.CanManageCurrentOrganizationAsync())
                return false;

            var orgId = await _organizationService.GetCurrentOrganizationIdAsync();
            if (!orgId.HasValue)
                return false;

            var active = await _context.OrganizationSubscriptions
                .Where(s => s.OrganizationId == orgId.Value && s.IsActive)
                .ToListAsync();

            foreach (var subscription in active)
            {
                subscription.IsActive = false;
                subscription.EndDate = DateTime.UtcNow;
            }

            var freePlan = await _context.SubscriptionPlans.FirstAsync(p => p.Name == AuthConstants.Free);
            _context.OrganizationSubscriptions.Add(new OrganizationSubscription
            {
                OrganizationId = orgId.Value,
                PlanId = freePlan.Id,
                IsActive = true,
                StartDate = DateTime.UtcNow
            });

            await _context.SaveChangesAsync();
            await _auditLogService.RecordAsync("CancelSubscription", "OrganizationSubscription", null, null, orgId.Value, "Cancelled subscription and moved organization to Free.");
            return true;
        }

        private static PricingPlanDto ToPricingDto(SubscriptionPlan plan, string currentPlan)
        {
            return new PricingPlanDto
            {
                Name = plan.Name,
                MaxQuestionsPerDay = plan.MaxQuestionsPerDay,
                MaxDocuments = plan.MaxDocuments,
                MaxSubjects = plan.MaxSubjects,
                MaxMembers = plan.MaxMembers,
                MaxFileSizeMb = plan.MaxFileSizeMb,
                AllowGemini = plan.AllowGemini,
                IsUnlimited = plan.IsUnlimited,
                MonthlyPrice = GetMonthlyPrice(plan.Name),
                Currency = "VND",
                IsCurrent = plan.Name == currentPlan
            };
        }

        private static CheckoutSessionDto ToCheckoutDto(CheckoutSession checkout, string planName)
        {
            return new CheckoutSessionDto
            {
                Id = checkout.Id,
                ReferenceCode = checkout.ReferenceCode,
                PlanName = planName,
                Amount = checkout.Amount,
                Currency = checkout.Currency,
                Status = checkout.Status,
                CreatedAt = checkout.CreatedAt
            };
        }

        private static decimal GetMonthlyPrice(string planName)
        {
            return planName switch
            {
                AuthConstants.Pro => 190000m,
                AuthConstants.Organization => 1500000m,
                _ => 0m
            };
        }
    }
}
