package cn.chinatelecom.cnos.inoe.auth.oauth2;

import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.TreeMap;
import java.util.UUID;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

/**
 * OAuth2 请求签名参考实现 / 测试数据生成器。
 *
 * 直接 main 运行，打印可粘贴进 oauth2-idp-test.http 的 authorize 请求体（含 timestamp/nonce/sign）。
 * 本类不依赖项目其它代码，可整体拷贝给外部对接方作为签名参考实现（仅用到 JDK 标准库）。
 *
 * 签名规则：对所有非空签名参数按 key 字典序升序拼成 key=value&key=value，
 *           再 HMAC-SHA256(clientSecret) 取小写 hex。client_secret 不参与传输。
 *
 * @author nj-likun
 * @version 1.0
 */
public class Oauth2SignDemo {

    public static void main(String[] args) {
        // —— 按实际情况修改 ——
        String clientId = "ndai";
        String clientSecret = "CGQlJs*Z@&X@a";
        String redirectUri = "https://extsysA.example.com/sso/callback";
        String phonenumber = "15888888888";
        String scope = "basic";
        String state = "xyz123";
        // 第②步：把 authorize 返回的 code 粘到这里，再运行即可同时生成 token 请求体；留空则只生成 authorize
        String code = "76471f74764f4ae0aeec108ad5250dd7";

        String timestamp = String.valueOf(System.currentTimeMillis());
        String nonce = UUID.randomUUID().toString().replace("-", "");

        TreeMap<String, String> params = new TreeMap<>();
        params.put("clientId", clientId);
        params.put("redirectUri", redirectUri);
        params.put("phonenumber", phonenumber);
        params.put("scope", scope);
        params.put("state", state);
        params.put("timestamp", timestamp);
        params.put("nonce", nonce);

        String canonical = canonical(params);
        String sign = hmacSha256Hex(clientSecret, canonical);

        System.out.println("canonical = " + canonical);
        System.out.println("sign      = " + sign);
        System.out.println();
        System.out.println("authorize 请求体：");
        System.out.println("{");
        System.out.println("  \"responseType\": \"code\",");
        System.out.println("  \"clientId\": \"" + clientId + "\",");
        System.out.println("  \"redirectUri\": \"" + redirectUri + "\",");
        System.out.println("  \"scope\": \"" + scope + "\",");
        System.out.println("  \"state\": \"" + state + "\",");
        System.out.println("  \"phonenumber\": \"" + phonenumber + "\",");
        System.out.println("  \"timestamp\": \"" + timestamp + "\",");
        System.out.println("  \"nonce\": \"" + nonce + "\",");
        System.out.println("  \"sign\": \"" + sign + "\"");
        System.out.println("}");

        // 第②步：填了 code 就同时生成 token 请求体
        if (code != null && !code.isEmpty()) {
            printToken(clientId, clientSecret, redirectUri, code);
        } else {
            System.out.println("\n[提示] 拿到 authorize 返回的 code 后，填入上面的 code 变量再次运行，即可生成 token 请求体。");
        }
    }

    /** 按 key 字典序拼接非空参数为 key=value&key=value */
    public static String canonical(TreeMap<String, String> params) {
        StringBuilder sb = new StringBuilder();
        for (Map.Entry<String, String> e : params.entrySet()) {
            if (e.getValue() == null || e.getValue().isEmpty()) {
                continue;
            }
            if (sb.length() > 0) {
                sb.append('&');
            }
            sb.append(e.getKey()).append('=').append(e.getValue());
        }
        return sb.toString();
    }

    /** HMAC-SHA256，返回小写 hex */
    public static String hmacSha256Hex(String secret, String data) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
            byte[] bytes = mac.doFinal(data.getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder(bytes.length * 2);
            for (byte b : bytes) {
                sb.append(Character.forDigit((b >> 4) & 0xF, 16));
                sb.append(Character.forDigit(b & 0xF, 16));
            }
            return sb.toString();
        } catch (Exception e) {
            throw new RuntimeException("HMAC-SHA256 计算失败", e);
        }
    }

    /**
     * ② 生成 token 请求体（签名字段集与 authorize 不同：clientId、code、redirectUri、timestamp、nonce）。
     * 用法：在 main 里调用 printToken(clientId, clientSecret, redirectUri, "上一步返回的code");
     */
    public static void printToken(String clientId, String clientSecret, String redirectUri, String code) {
        String timestamp = String.valueOf(System.currentTimeMillis());
        String nonce = UUID.randomUUID().toString().replace("-", "");

        TreeMap<String, String> params = new TreeMap<>();
        params.put("clientId", clientId);
        params.put("code", code);
        params.put("redirectUri", redirectUri);
        params.put("timestamp", timestamp);
        params.put("nonce", nonce);

        String canonical = canonical(params);
        String sign = hmacSha256Hex(clientSecret, canonical);

        System.out.println();
        System.out.println("===== ② /auth/oauth2/token =====");
        System.out.println("canonical = " + canonical);
        System.out.println("sign      = " + sign);
        System.out.println("token 请求体：");
        System.out.println("{");
        System.out.println("  \"grantType\": \"authorization_code\",");
        System.out.println("  \"code\": \"" + code + "\",");
        System.out.println("  \"clientId\": \"" + clientId + "\",");
        System.out.println("  \"redirectUri\": \"" + redirectUri + "\",");
        System.out.println("  \"timestamp\": \"" + timestamp + "\",");
        System.out.println("  \"nonce\": \"" + nonce + "\",");
        System.out.println("  \"sign\": \"" + sign + "\"");
        System.out.println("}");
    }
}
