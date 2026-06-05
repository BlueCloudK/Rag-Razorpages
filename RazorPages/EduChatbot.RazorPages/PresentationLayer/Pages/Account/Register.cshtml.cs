using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using ServiceLayer.Models;
using ServiceLayer.Services;

namespace PresentationLayer.Pages.Account;

[AllowAnonymous]
public class RegisterModel : PageModel
{
    private readonly IAuthService _authService;

    public RegisterModel(IAuthService authService)
    {
        _authService = authService;
    }

    [BindProperty]
    public RegisterInput Input { get; set; } = new();

    public async Task<IActionResult> OnPostAsync()
    {
        var result = await _authService.RegisterStudentAsync(Input);
        if (result.Success)
            return RedirectToPage("/Index");

        ModelState.AddModelError(string.Empty, result.Message);
        foreach (var error in result.Errors)
            ModelState.AddModelError(string.Empty, error);

        return Page();
    }
}
