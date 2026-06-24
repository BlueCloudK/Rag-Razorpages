using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc.RazorPages;
using ServiceLayer.Models;
using ServiceLayer.Services;

namespace PresentationLayer.Pages;

[Authorize(Roles = AuthConstants.Admin)]
public class RagLabModel : PageModel
{
    private readonly IRagLabService _ragLabService;

    public RagLabModel(IRagLabService ragLabService)
    {
        _ragLabService = ragLabService;
    }

    public RagLabDashboardDto Data { get; private set; } = new();

    public async Task OnGetAsync()
    {
        Data = await _ragLabService.GetDashboardAsync();
    }
}
