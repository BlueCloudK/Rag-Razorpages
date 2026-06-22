using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using ServiceLayer.Models;
using ServiceLayer.Services;

namespace EduChatbot.RazorPages.Pages.Billing;

[Authorize(Roles = AuthConstants.Admin)]
public class CheckoutModel : PageModel
{
    private readonly IBillingService _billingService;

    public CheckoutModel(IBillingService billingService)
    {
        _billingService = billingService;
    }

    public CheckoutSessionDto Checkout { get; private set; } = new();

    public async Task<IActionResult> OnGetAsync(int id)
    {
        var checkout = await _billingService.GetCheckoutAsync(id);
        if (checkout == null)
        {
            return NotFound();
        }

        Checkout = checkout;
        return Page();
    }

    public async Task<IActionResult> OnPostPayAsync(int id)
    {
        await _billingService.PayCheckoutAsync(id);
        return RedirectToPage("/Billing/Index");
    }
}
