<?php
declare(strict_types=1);

function check(bool $ok, string $message): void {
    if (!$ok) {
        throw new RuntimeException($message);
    }
}
function numeric(int $seed): int {
    $sum = 0;
    for ($i = 0; $i < 300; $i++) {
        $sum += (($i * 31 + $seed) % 997);
    }
    return $sum;
}
function floating(float $seed): float {
    for ($i = 0; $i < 150; $i++) {
        $seed = $seed * 0.995 + 0.125;
    }
    return $seed;
}
function maybeExit(bool $exit): int {
    if ($exit) {
        exit(37);
    }
    return numeric(3);
}
function silencedYield(): int {
    $level = error_reporting();
    Swoole\Coroutine::sleep(0.001);
    check(error_reporting() === $level, 'silenced error_reporting lost across yield');
    return $level;
}

check(extension_loaded('swoole'), 'Swoole missing');
check(!function_exists('swoole_call_array_method'), 'stdext still enabled');
$before = opcache_get_status(false)['jit'];
$sum = 0;
$float = 0.0;
for ($i = 0; $i < 1200; $i++) {
    $sum += numeric($i % 10);
    $float += floating((float) ($i % 10));
    maybeExit(false);
}
$after = opcache_get_status(false)['jit'];
$events = [];
Swoole\Coroutine\run(function () use (&$events): void {
    $channel = new Swoole\Coroutine\Channel(1);
    Swoole\Coroutine::create(function () use ($channel): void {
        for ($i = 0; $i < 100; $i++) {
            $channel->push(numeric($i % 10));
            Swoole\Coroutine::sleep(0.0001);
        }
    });
    $total = 0;
    for ($i = 0; $i < 100; $i++) {
        $total += $channel->pop();
    }
    check($total === array_sum(array_map('numeric', array_map(fn($i) => $i % 10, range(0, 99)))), 'channel result mismatch');
    $events[] = 'channel';
    try {
        Swoole\Coroutine::sleep(0.001);
        throw new LogicException('after-yield');
    } catch (LogicException $e) {
        check($e->getMessage() === 'after-yield', 'exception changed');
        $events[] = 'exception';
    }
    $normal = error_reporting();
    @silencedYield();
    check(error_reporting() === $normal, 'error_reporting not restored');
    $events[] = 'silence';
    $server = new Swoole\Coroutine\Socket(AF_INET, SOCK_STREAM, 0);
    check($server->bind('127.0.0.1', 0) && $server->listen(), 'TCP listen failed');
    $port = $server->getsockname()['port'];
    Swoole\Coroutine::create(function () use ($server): void {
        $peer = $server->accept(3);
        check($peer !== false, 'TCP accept failed');
        check($peer->recv(3) === 'ping', 'TCP receive failed');
        check($peer->sendAll('pong') === 4, 'TCP send failed');
        $peer->close();
        $server->close();
    });
    $client = new Swoole\Coroutine\Socket(AF_INET, SOCK_STREAM, 0);
    check($client->connect('127.0.0.1', $port, 3), 'TCP connect failed');
    $client->sendAll('ping');
    check($client->recv(3) === 'pong', 'TCP round trip failed');
    $client->close();
    $events[] = 'tcp';
    try {
        maybeExit(true);
        throw new RuntimeException('exit did not throw');
    } catch (Swoole\ExitException $e) {
        check($e->getStatus() === 37, 'coroutine exit status changed');
        check(($e->getFlags() & SWOOLE_EXIT_IN_COROUTINE) !== 0, 'coroutine exit flag missing');
        $events[] = 'exit';
    }
});
check($events === ['channel', 'exception', 'silence', 'tcp', 'exit'], 'coroutine checks incomplete');
echo 'JIT_REPORT:', json_encode([
    'php' => PHP_VERSION,
    'swoole' => swoole_version(),
    'stdext' => function_exists('swoole_call_array_method'),
    'before' => $before,
    'after' => $after,
    'machine_code_bytes' => $before['buffer_free'] - $after['buffer_free'],
    'integer_result' => $sum,
    'float_result' => $float,
    'coroutines' => $events,
], JSON_THROW_ON_ERROR), "\n";
