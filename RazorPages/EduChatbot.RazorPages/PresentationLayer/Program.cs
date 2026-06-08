using PresentationLayer.Hubs;
using PresentationLayer.Services;
using ServiceLayer.Services;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddRazorPages();
builder.Services.AddSignalR();
builder.Services.AddEduChatbotServices(builder.Configuration);
builder.Services.AddScoped<IRealtimeNotificationService, SignalRRealtimeNotificationService>();

builder.Services.AddHttpClient("AiService", client =>
{
    client.BaseAddress = new Uri(builder.Configuration["AiService:BaseUrl"] ?? "http://127.0.0.1:8000");
    client.Timeout = TimeSpan.FromMinutes(30);
});

var app = builder.Build();

await app.Services.InitializeEduChatbotDatabaseAsync(app.Environment.IsDevelopment());

if (!app.Environment.IsDevelopment())
{
    app.UseExceptionHandler("/Error");
}

app.UseRouting();
app.UseStaticFiles();
app.UseAuthentication();
app.UseAuthorization();

app.MapRazorPages();
app.MapHub<WorkspaceHub>("/hubs/workspace");

app.Run();
