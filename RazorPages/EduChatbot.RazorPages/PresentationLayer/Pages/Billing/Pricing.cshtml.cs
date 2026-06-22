using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using ServiceLayer.Models;
using ServiceLayer.Services;

namespace EduChatbot.RazorPages.Pages.Billing;

[Authorize(Roles = AuthConstants.Admin)]
public class PricingModel : PageModel
{
    private readonly IBillingService _billingService;

    public PricingModel(IBillingService billingService)
    {
        _billingService = billingService;
    }

    public IList<PricingPlanDto> Plans { get; private set; } = new List<PricingPlanDto>();

    public async Task OnGetAsync()
    {
        Plans = await _billingService.GetPricingAsync();
    }

    public async Task<IActionResult> OnPostCheckoutAsync(string planName)
    {
        var checkout = await _billingService.StartCheckoutAsync(planName);
        if (checkout == null)
        {
            return RedirectToPage("/Billing/Index");
        }

        return RedirectToPage("/Billing/Checkout", new { id = checkout.Id });
    }
}
