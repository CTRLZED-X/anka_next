using System.Net;
using System.Net.Sockets;
using System.Text;

namespace DofusCoordinateBridge;

public sealed class LocalHttpServer : IDisposable
{
    private readonly TcpListener _listener;
    private readonly Func<string, string, string> _handler;
    private readonly CancellationTokenSource _stop = new();
    private Thread _thread;

    public LocalHttpServer(int port, Func<string, string, string> handler)
    {
        _listener = new TcpListener(IPAddress.Loopback, port);
        _handler = handler;
    }

    public void Start()
    {
        _listener.Start();
        _thread = new Thread(Run) { IsBackground = true, Name = "DofusCoordinateBridge" };
        _thread.Start();
    }

    public void Dispose()
    {
        _stop.Cancel();
        _listener.Stop();
    }

    private void Run()
    {
        while (!_stop.IsCancellationRequested)
        {
            try
            {
                using var client = _listener.AcceptTcpClient();
                client.ReceiveTimeout = 5000;
                client.SendTimeout = 5000;
                HandleClient(client);
            }
            catch (SocketException) when (_stop.IsCancellationRequested)
            {
                return;
            }
            catch
            {
                // A malformed local request must not stop the bridge.
            }
        }
    }

    private void HandleClient(TcpClient client)
    {
        using var stream = client.GetStream();
        using var reader = new StreamReader(stream, Encoding.UTF8, false, 4096, true);
        var requestLine = reader.ReadLine() ?? "";
        var requestParts = requestLine.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        if (requestParts.Length < 2)
        {
            WriteResponse(stream, 400, "{\"status\":\"BAD_REQUEST\"}");
            return;
        }

        var method = requestParts[0].ToUpperInvariant();
        var route = requestParts[1].Split('?', 2)[0];
        var contentLength = 0;
        string line;
        while (!string.IsNullOrEmpty(line = reader.ReadLine()))
        {
            var separator = line.IndexOf(':');
            if (separator < 0) continue;
            if (line[..separator].Equals("Content-Length", StringComparison.OrdinalIgnoreCase))
            {
                int.TryParse(line[(separator + 1)..].Trim(), out contentLength);
            }
        }

        if ((route == "/resolve" || route == "/resolve_fight_entry" || route == "/discover" || route == "/observe") && method != "POST")
        {
            WriteResponse(stream, 405, "{\"status\":\"METHOD_NOT_ALLOWED\"}");
            return;
        }
        if ((route == "/health" || route == "/automation" || route == "/coordinates") && method != "GET")
        {
            WriteResponse(stream, 405, "{\"status\":\"METHOD_NOT_ALLOWED\"}");
            return;
        }
        if (route is not ("/resolve" or "/resolve_fight_entry" or "/discover" or "/observe" or "/health" or "/automation" or "/coordinates"))
        {
            WriteResponse(stream, 404, "{\"status\":\"NOT_FOUND\"}");
            return;
        }

        var body = "";
        if (contentLength > 0)
        {
            if (contentLength > 1024 * 1024)
            {
                WriteResponse(stream, 413, "{\"status\":\"PAYLOAD_TOO_LARGE\"}");
                return;
            }
            var buffer = new char[contentLength];
            var read = 0;
            while (read < contentLength)
            {
                var count = reader.Read(buffer, read, contentLength - read);
                if (count <= 0) break;
                read += count;
            }
            body = new string(buffer, 0, read);
        }

        WriteResponse(stream, 200, _handler(route, body));
    }

    private static void WriteResponse(Stream stream, int status, string body)
    {
        var payload = Encoding.UTF8.GetBytes(body);
        var reason = status switch
        {
            200 => "OK",
            400 => "Bad Request",
            404 => "Not Found",
            405 => "Method Not Allowed",
            413 => "Payload Too Large",
            _ => "Error"
        };
        var headers = Encoding.ASCII.GetBytes(
            $"HTTP/1.1 {status} {reason}\r\n" +
            "Content-Type: application/json; charset=utf-8\r\n" +
            $"Content-Length: {payload.Length}\r\n" +
            "Connection: close\r\n\r\n"
        );
        stream.Write(headers);
        stream.Write(payload);
    }
}
