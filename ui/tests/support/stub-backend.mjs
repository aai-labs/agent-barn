import { createServer } from "node:http";

const PORT = Number(process.env.STUB_BACKEND_PORT ?? 3013);

createServer((request, response) => {
  request.resume();
  response.writeHead(500, { "Content-Type": "text/plain" });
  response.end("Internal Server Error");
}).listen(PORT, "127.0.0.1");
