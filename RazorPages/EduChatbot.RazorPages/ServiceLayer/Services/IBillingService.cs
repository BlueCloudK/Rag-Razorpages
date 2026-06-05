using System.Collections.Generic;
using System.Threading.Tasks;
using ServiceLayer.Models;

namespace ServiceLayer.Services
{
    public interface IBillingService
    {
        Task<List<PricingPlanDto>> GetPricingAsync();
        Task<BillingPortalDto> GetPortalAsync();
        Task<CheckoutSessionDto?> StartCheckoutAsync(string planName);
        Task<CheckoutSessionDto?> GetCheckoutAsync(int id);
        Task<bool> PayCheckoutAsync(int id);
        Task<bool> CancelSubscriptionAsync();
    }
}
