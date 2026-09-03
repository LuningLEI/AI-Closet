import Combine
import Foundation
import SwiftUI

enum AppLanguage: String, CaseIterable, Identifiable {
    case english = "en"
    case simplifiedChinese = "zh-Hans"

    var id: String { rawValue }

    var locale: Locale {
        Locale(identifier: rawValue)
    }
}

enum TemperatureUnitPreference: String, CaseIterable, Identifiable {
    case fahrenheit
    case celsius

    var id: String { rawValue }
}

@MainActor
final class AppSettings: ObservableObject {
    private enum StorageKeys {
        static let language = "app.settings.language"
        static let temperatureUnit = "app.settings.temperatureUnit"
    }

    @Published var language: AppLanguage {
        didSet { defaults.set(language.rawValue, forKey: StorageKeys.language) }
    }

    @Published var temperatureUnit: TemperatureUnitPreference {
        didSet { defaults.set(temperatureUnit.rawValue, forKey: StorageKeys.temperatureUnit) }
    }

    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        self.language = AppLanguage(rawValue: defaults.string(forKey: StorageKeys.language) ?? "") ?? .english
        self.temperatureUnit = TemperatureUnitPreference(rawValue: defaults.string(forKey: StorageKeys.temperatureUnit) ?? "") ?? .fahrenheit
    }

    var locale: Locale {
        language.locale
    }

    func text(_ key: String, _ args: CVarArg...) -> String {
        let template = Self.catalog[language]?[key] ?? Self.catalog[.english]?[key] ?? key
        guard !args.isEmpty else { return template }
        return String(format: template, locale: locale, arguments: args)
    }

    func option(_ rawValue: String) -> String {
        let normalizedKey = "option." + Self.normalizedOptionKey(rawValue)
        return Self.catalog[language]?[normalizedKey] ?? Self.catalog[.english]?[normalizedKey] ?? rawValue
    }

    func displayedTemperature(fahrenheit: Double) -> String {
        switch temperatureUnit {
        case .fahrenheit:
            return "\(Int(fahrenheit.rounded()))F"
        case .celsius:
            let celsius = Int(((fahrenheit - 32) * 5 / 9).rounded())
            return "\(celsius)C"
        }
    }

    func resolvedText(_ value: String) -> String {
        guard value.hasPrefix("l10n:") else { return value }
        return text(String(value.dropFirst(5)))
    }

    private static func normalizedOptionKey(_ rawValue: String) -> String {
        rawValue
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
            .replacingOccurrences(of: "[^a-z0-9]+", with: "_", options: .regularExpression)
            .trimmingCharacters(in: CharacterSet(charactersIn: "_"))
    }

    private static let catalog: [AppLanguage: [String: String]] = [
        .english: [
            "tab.today": "Today",
            "tab.closet": "Closet",
            "tab.recommendations": "Recommendations",
            "tab.my": "My",
            "auth.subtitle.sign_in": "Sign in to your private wardrobe",
            "auth.subtitle.sign_up": "Create your closet account",
            "auth.email": "Email",
            "auth.password": "Password",
            "auth.action.sign_in": "Sign in",
            "auth.action.create_account": "Create account",
            "auth.toggle.sign_up": "New here? Create an account",
            "auth.toggle.sign_in": "Already have an account? Sign in",
            "profile.greeting": "Hi,",
            "profile.default_nickname": "Closet user",
            "profile.section.planner": "Occasion planner",
            "profile.section.basic": "Basic profile",
            "profile.section.style": "Style preference",
            "profile.section.catalog": "Catalog tags",
            "profile.section.settings": "System settings",
            "profile.section.settings.subtitle": "%@ · %@",
            "profile.section.catalog.subtitle": "%d active categories",
            "profile.sign_out.prompt": "Sign out of AI Closet?",
            "profile.sign_out": "Sign out",
            "common.cancel": "Cancel",
            "common.save": "Save",
            "common.done": "Done",
            "profile.edit.planner_settings": "Planner settings",
            "profile.edit.weekday_default": "Weekday default",
            "profile.edit.holiday_rule": "Holiday rule",
            "profile.edit.skip_holidays": "Skip U.S. federal holidays",
            "profile.edit.nickname": "Nickname",
            "profile.edit.birth_year": "Birth year",
            "profile.edit.gender": "Gender",
            "profile.edit.daily_occasions": "Daily occasions",
            "profile.edit.preferred_styles": "Preferred styles",
            "profile.edit.recognition_categories": "Recognition categories",
            "profile.edit.custom_tag": "Add custom tag",
            "profile.edit.custom_tags": "Custom tags",
            "common.add": "Add",
            "profile.edit.allow_training": "Allow anonymized future model improvement",
            "profile.edit.update_later": "You can update these settings later from My.",
            "profile.page.setup": "Set up your closet profile",
            "common.back": "Back",
            "common.next": "Next",
            "profile.finish_setup": "Finish setup",
            "profile.loading": "Loading profile",
            "settings.title": "System settings",
            "settings.language": "Language",
            "settings.temperature_unit": "Temperature unit",
            "settings.language.english": "English",
            "settings.language.chinese": "Chinese",
            "settings.temperature.fahrenheit": "Fahrenheit",
            "settings.temperature.celsius": "Celsius",
            "today.city_placeholder": "Enter a city",
            "today.update": "Update",
            "today.weather_unavailable": "Weather unavailable",
            "today.loading_weather": "Loading weather",
            "today.loading_outfits": "Finding outfits",
            "today.no_recommendations": "No recommendations yet",
            "today.recommendations_unavailable": "Recommendations unavailable",
            "today.recommendations_empty": "Add analyzed closet items to get today's outfit.",
            "today.occasion": "Today's occasion",
            "today.city_required": "Enter a city to load weather.",
            "recommendations.title": "Recommendations",
            "recommendations.occasion": "Occasion",
            "recommendations.style": "Style",
            "recommendations.color": "Color",
            "recommendations.temperature": "Temperature %@",
            "recommendations.generate": "Generate",
            "recommendations.loading": "Scoring outfits",
            "recommendations.no_matches": "No strong matches",
            "recommendations.no_matches_desc": "Add more analyzed closet items or adjust the filters.",
            "recommendations.chat_open": "Open Agent Chat",
            "common.any": "Any",
            "common.not_set_birth_year": "Birth year not set",
            "common.no_saved_occasion": "No saved occasion yet",
            "option.everyday": "Everyday",
            "option.work": "Work",
            "option.school": "School",
            "option.date": "Date",
            "option.party": "Party",
            "option.travel": "Travel",
            "option.formal": "Formal",
            "option.workout": "Workout",
            "option.casual": "Casual",
            "option.elegant": "Elegant",
            "option.streetwear": "Streetwear",
            "option.minimal": "Minimal",
            "option.romantic": "Romantic",
            "option.classic": "Classic",
            "option.sporty": "Sporty",
            "option.business": "Business",
            "option.prefer_not_to_say": "Prefer not to say",
            "option.woman": "Woman",
            "option.man": "Man",
            "option.non_binary": "Non-binary",
            "option.self_describe": "Self-describe",
            "option.tops": "Tops",
            "option.bottoms": "Bottoms",
            "option.dresses": "Dresses",
            "option.jumpsuits": "Jumpsuits",
            "option.sets": "Sets",
            "option.outerwear": "Outerwear",
            "option.shoes": "Shoes",
            "option.bags": "Bags",
            "option.accessories": "Accessories",
            "option.activewear": "Activewear",
            "option.swimwear": "Swimwear",
            "option.intimates": "Intimates",
            "option.uncategorized": "Uncategorized"
        ],
        .simplifiedChinese: [
            "tab.today": "今日",
            "tab.closet": "衣橱",
            "tab.recommendations": "推荐",
            "tab.my": "我的",
            "auth.subtitle.sign_in": "登录你的私人衣橱",
            "auth.subtitle.sign_up": "创建你的衣橱账号",
            "auth.email": "邮箱",
            "auth.password": "密码",
            "auth.action.sign_in": "登录",
            "auth.action.create_account": "创建账号",
            "auth.toggle.sign_up": "第一次来？创建账号",
            "auth.toggle.sign_in": "已有账号？去登录",
            "profile.greeting": "Hi,",
            "profile.default_nickname": "Closet 用户",
            "profile.section.planner": "场合日历",
            "profile.section.basic": "基础资料",
            "profile.section.style": "风格偏好",
            "profile.section.catalog": "分类标签",
            "profile.section.settings": "系统设置",
            "profile.section.settings.subtitle": "%@ · %@",
            "profile.section.catalog.subtitle": "%d 个启用分类",
            "profile.sign_out.prompt": "要退出 AI Closet 吗？",
            "profile.sign_out": "退出登录",
            "common.cancel": "取消",
            "common.save": "保存",
            "common.done": "完成",
            "profile.edit.planner_settings": "日历设置",
            "profile.edit.weekday_default": "工作日默认场合",
            "profile.edit.holiday_rule": "节假日规则",
            "profile.edit.skip_holidays": "跳过美国法定节假日",
            "profile.edit.nickname": "昵称",
            "profile.edit.birth_year": "出生年份",
            "profile.edit.gender": "性别",
            "profile.edit.daily_occasions": "日常场合",
            "profile.edit.preferred_styles": "偏好风格",
            "profile.edit.recognition_categories": "识别分类",
            "profile.edit.custom_tag": "添加自定义标签",
            "profile.edit.custom_tags": "自定义标签",
            "common.add": "添加",
            "profile.edit.allow_training": "允许匿名用于后续模型改进",
            "profile.edit.update_later": "这些设置之后也可以在“我的”里修改。",
            "profile.page.setup": "设置你的衣橱资料",
            "common.back": "返回",
            "common.next": "下一步",
            "profile.finish_setup": "完成设置",
            "profile.loading": "正在加载资料",
            "settings.title": "系统设置",
            "settings.language": "语言",
            "settings.temperature_unit": "温度单位",
            "settings.language.english": "English",
            "settings.language.chinese": "中文",
            "settings.temperature.fahrenheit": "华氏度",
            "settings.temperature.celsius": "摄氏度",
            "today.city_placeholder": "输入城市",
            "today.update": "更新",
            "today.weather_unavailable": "天气不可用",
            "today.loading_weather": "正在加载天气",
            "today.loading_outfits": "正在寻找搭配",
            "today.no_recommendations": "暂时还没有推荐",
            "today.recommendations_unavailable": "推荐不可用",
            "today.recommendations_empty": "先添加并分析衣橱单品，才能生成今日穿搭。",
            "today.occasion": "今天的场合",
            "today.city_required": "请输入城市以加载天气。",
            "recommendations.title": "推荐",
            "recommendations.occasion": "场合",
            "recommendations.style": "风格",
            "recommendations.color": "颜色",
            "recommendations.temperature": "温度 %@",
            "recommendations.generate": "生成",
            "recommendations.loading": "正在评分搭配",
            "recommendations.no_matches": "暂时没有强匹配",
            "recommendations.no_matches_desc": "多添加一些已分析衣物，或调整筛选条件。",
            "recommendations.chat_open": "打开 AI 聊天",
            "common.any": "不限",
            "common.not_set_birth_year": "未设置出生年份",
            "common.no_saved_occasion": "还没有保存场合",
            "option.everyday": "日常",
            "option.work": "工作",
            "option.school": "上学",
            "option.date": "约会",
            "option.party": "派对",
            "option.travel": "旅行",
            "option.formal": "正式",
            "option.workout": "运动",
            "option.casual": "休闲",
            "option.elegant": "优雅",
            "option.streetwear": "街头",
            "option.minimal": "极简",
            "option.romantic": "浪漫",
            "option.classic": "经典",
            "option.sporty": "运动风",
            "option.business": "商务",
            "option.prefer_not_to_say": "不想透露",
            "option.woman": "女性",
            "option.man": "男性",
            "option.non_binary": "非二元",
            "option.self_describe": "自行描述",
            "option.tops": "上装",
            "option.bottoms": "下装",
            "option.dresses": "连衣裙",
            "option.jumpsuits": "连体装",
            "option.sets": "套装",
            "option.outerwear": "外套",
            "option.shoes": "鞋子",
            "option.bags": "包袋",
            "option.accessories": "配饰",
            "option.activewear": "运动服",
            "option.swimwear": "泳装",
            "option.intimates": "内搭",
            "option.uncategorized": "未分类"
        ]
    ]
}
