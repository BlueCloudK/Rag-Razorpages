using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using ServiceLayer.Models;
using ServiceLayer.Services;

namespace PresentationLayer.Pages.Admin;

[Authorize(Roles = AuthConstants.Admin)]
public class UsersModel : PageModel
{
    private readonly IAdminService _adminService;

    public UsersModel(IAdminService adminService)
    {
        _adminService = adminService;
    }

    public AdminUserManagementDto Data { get; set; } = new();

    public async Task OnGetAsync()
    {
        Data = await _adminService.GetUsersAsync();
    }

    public async Task<IActionResult> OnPostAsync(AdminEditUserInput input)
    {
        await _adminService.UpdateUserAsync(input);
        return RedirectToPage();
    }

    public async Task<IActionResult> OnPostCreateAsync(AdminCreateUserInput input)
    {
        var result = await _adminService.CreateUserAsync(input);
        TempData[result.Success ? "SuccessMessage" : "ErrorMessage"] = result.Message;
        return RedirectToPage();
    }
}
