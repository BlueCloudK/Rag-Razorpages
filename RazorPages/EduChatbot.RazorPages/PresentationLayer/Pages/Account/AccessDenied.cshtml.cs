using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc.RazorPages;

namespace PresentationLayer.Pages.Account;

[AllowAnonymous]
public class AccessDeniedModel : PageModel
{
}
