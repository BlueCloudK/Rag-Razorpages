using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using ServiceLayer.Models;
using ServiceLayer.Services;

namespace EduChatbot.RazorPages.Pages.Billing;

[Authorize(Roles = AuthConstants.Admin)]
public class IndexModel : PageModel
{
    private readonly IBillingService _billingService;

    public IndexModel(IBillingService billingService)
    {
        _billingService = billingService;
    }

    public BillingPortalDto Portal { get; private set; } = new();

    public async Task OnGetAsync()
    {
        Portal = await _billingService.GetPortalAsync();
    }

    public async Task<IActionResult> OnPostCancelAsync()
    {
        await _billingService.CancelSubscriptionAsync();
        return RedirectToPage();
    }
}
