using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using ServiceLayer.Models;
using ServiceLayer.Services;

namespace PresentationLayer.Pages.Admin;

[Authorize(Roles = AuthConstants.Admin)]
public class MembershipsModel : PageModel
{
    private readonly IAdminService _adminService;

    public MembershipsModel(IAdminService adminService)
    {
        _adminService = adminService;
    }

    public AdminMembershipManagementDto Data { get; set; } = new();

    public async Task OnGetAsync()
    {
        Data = await _adminService.GetMembershipsAsync();
    }

    public async Task<IActionResult> OnPostAddAsync(AdminMembershipInput input)
    {
        await _adminService.AddMembershipAsync(input);
        return RedirectToPage();
    }

    public async Task<IActionResult> OnPostRemoveAsync(int membershipId)
    {
        await _adminService.RemoveMembershipAsync(membershipId);
        return RedirectToPage();
    }
}
